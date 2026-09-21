"""Companies House Async HTTP Client.

Features:
- HTTP Basic Auth with API Key
- Async I/O with httpx
- Concurrency limiting via asyncio.Semaphore
- In-memory response caching with TTL
- Automatic retry with backoff on 429 Too Many Requests
- Graceful 404 handling
"""

import asyncio
import base64
import time
import logging
from typing import Optional, Dict, Any
import httpx

from app.core.config import settings
from app.models.raw_companies_house import (
    CHCompanyProfile,
    CHOfficersResponse,
    CHAppointmentsResponse,
    CHPSCsResponse,
    CHSearchResponse,
)

logger = logging.getLogger("companies_house_client")

class CompaniesHouseClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.COMPANIES_HOUSE_API_KEY
        self.base_url = (base_url or settings.COMPANIES_HOUSE_BASE_URL).rstrip("/")
        
        # Prepare Basic Auth header (username = api_key, password = empty)
        auth_bytes = f"{self.api_key}:".encode("utf-8")
        self.auth_header = f"Basic {base64.b64encode(auth_bytes).decode('ascii')}"
        
        # Concurrency limit: max 5 concurrent requests
        self._semaphore = asyncio.Semaphore(5)
        
        # Simple in-memory cache: path -> (timestamp, data)
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._cache_ttl = settings.CACHE_TTL_SECONDS
        
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=10.0),
                headers={
                    "Authorization": self.auth_header,
                    "Accept": "application/json",
                    "User-Agent": "ClearView-Compliance-Engine/1.0",
                }
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _fetch(self, path: str, retries: int = 3) -> Optional[Dict[str, Any]]:
        # Check cache
        now = time.time()
        if path in self._cache:
            ts, cached_data = self._cache[path]
            if now - ts < self._cache_ttl:
                return cached_data

        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        
        async with self._semaphore:
            client = await self.get_client()
            backoff = 1.0
            
            for attempt in range(retries):
                try:
                    resp = await client.get(url)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        self._cache[path] = (now, data)
                        return data
                    
                    if resp.status_code == 404:
                        logger.debug(f"Companies House 404 on {path}")
                        return None
                    
                    if resp.status_code == 429:
                        # Rate limited
                        retry_after = resp.headers.get("Retry-After")
                        sleep_time = float(retry_after) if retry_after else backoff
                        logger.warning(f"Rate limited by CH API. Waiting {sleep_time}s on attempt {attempt+1}")
                        await asyncio.sleep(sleep_time)
                        backoff *= 2
                        continue
                    
                    if resp.status_code in (500, 502, 503, 504):
                        logger.warning(f"CH Server Error {resp.status_code}. Retrying in {backoff}s...")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    
                    resp.raise_for_status()
                    
                except httpx.RequestError as e:
                    logger.error(f"Network error on {url}: {e}. Retrying ({attempt+1}/{retries})...")
                    await asyncio.sleep(backoff)
                    backoff *= 2
            
            logger.error(f"Failed to fetch {url} after {retries} retries.")
            return None

    async def get_company(self, company_number: str) -> Optional[CHCompanyProfile]:
        clean_num = company_number.strip().zfill(8) if company_number.strip().isdigit() else company_number.strip().upper()
        data = await self._fetch(f"/company/{clean_num}")
        if not data:
            return None
        return CHCompanyProfile.model_validate(data)

    async def get_officers(self, company_number: str) -> CHOfficersResponse:
        clean_num = company_number.strip().zfill(8) if company_number.strip().isdigit() else company_number.strip().upper()
        data = await self._fetch(f"/company/{clean_num}/officers?items_per_page=100")
        if not data:
            return CHOfficersResponse(items=[], total_results=0)
        return CHOfficersResponse.model_validate(data)

    async def get_officer_appointments(self, appointments_path_or_id: str) -> CHAppointmentsResponse:
        """Fetch all historical/current appointments for an officer.
        Accepts either '/officers/AbC123XyZ/appointments' or just 'AbC123XyZ'.
        """
        path = appointments_path_or_id.strip()
        if not path.startswith("/"):
            path = f"/officers/{path}/appointments"
        if not path.endswith("/appointments"):
            path = f"{path}/appointments"
            
        data = await self._fetch(f"{path}?items_per_page=50")
        if not data:
            return CHAppointmentsResponse(items=[], total_results=0)
        return CHAppointmentsResponse.model_validate(data)

    async def get_pscs(self, company_number: str) -> CHPSCsResponse:
        clean_num = company_number.strip().zfill(8) if company_number.strip().isdigit() else company_number.strip().upper()
        data = await self._fetch(f"/company/{clean_num}/persons-with-significant-control?items_per_page=50")
        if not data:
            return CHPSCsResponse(items=[], total_results=0)
        return CHPSCsResponse.model_validate(data)

    async def get_exemptions(self, company_number: str) -> Optional[Dict[str, Any]]:
        clean_num = company_number.strip().zfill(8) if company_number.strip().isdigit() else company_number.strip().upper()
        data = await self._fetch(f"/company/{clean_num}/exemptions")
        return data

    async def search_companies(self, query: str, items_per_page: int = 10) -> CHSearchResponse:
        data = await self._fetch(f"/search/companies?q={httpx.URL('', params={'q': query}).params['q']}&items_per_page={items_per_page}")
        if not data:
            return CHSearchResponse(items=[], total_results=0)
        return CHSearchResponse.model_validate(data)

# Singleton instance
ch_client = CompaniesHouseClient()
