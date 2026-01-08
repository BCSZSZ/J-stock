"""
J-Quants API V2 Client
Implements rate-limited requests to J-Quants API V2 endpoints.
"""
import time
import logging
from typing import Dict, List, Optional, Any
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class JQuantsV2Client:
    """
    J-Quants API V2 Client with rate limiting and pagination support.
    
    Rate Limit: Light Plan (60 req/min) = 1 req/sec.
    """
    
    BASE_URL = "https://api.jquants.com"
    RATE_LIMIT_DELAY = 1.0  # seconds between requests
    MAX_RETRIES = 3
    RETRY_WAIT = 5  # seconds to wait on 429
    
    def __init__(self, api_key: str):
        """
        Initialize the J-Quants V2 Client.
        
        Args:
            api_key: Your J-Quants API key.
        """
        self.api_key = api_key
        self.headers = {"x-api-key": api_key}
        self.last_request_time = 0.0
        
    def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self.last_request_time = time.time()
    
    def _make_request(
        self, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make a rate-limited GET request with retry logic.
        
        Args:
            endpoint: API endpoint path (e.g., '/v2/equities/bars/daily').
            params: Query parameters.
            
        Returns:
            JSON response as dictionary.
            
        Raises:
            requests.HTTPError: On non-retryable errors.
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        for attempt in range(self.MAX_RETRIES):
            self._rate_limit()
            
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
                
                if response.status_code == 429:
                    logger.warning(f"Rate limit hit (429). Waiting {self.RETRY_WAIT}s...")
                    time.sleep(self.RETRY_WAIT)
                    continue
                    
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.HTTPError as e:
                if attempt == self.MAX_RETRIES - 1:
                    logger.error(f"Request failed after {self.MAX_RETRIES} attempts: {e}")
                    raise
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying...")
                time.sleep(2)
                
        return {}
    
    def _fetch_paginated(
        self, 
        endpoint: str, 
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Fetch all pages from a paginated endpoint.
        
        Args:
            endpoint: API endpoint path.
            params: Initial query parameters.
            
        Returns:
            Combined list of all records across pages.
        """
        all_data = []
        pagination_key = None
        
        while True:
            if pagination_key:
                params['pagination_key'] = pagination_key
            
            response = self._make_request(endpoint, params)
            
            # Extract data (key varies by endpoint)
            data = response.get('data', response.get('bars', []))
            if not data:
                break
                
            all_data.extend(data)
            
            # Check for next page
            pagination_key = response.get('pagination_key')
            if not pagination_key:
                break
                
            logger.info(f"Fetching next page (key: {pagination_key[:20]}...)")
            
        return all_data
    
    def get_daily_bars(
        self, 
        code: str, 
        from_date: str, 
        to_date: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch daily OHLC bars for a stock.
        
        Args:
            code: Stock code (e.g., '6758').
            from_date: Start date (YYYY-MM-DD).
            to_date: End date (YYYY-MM-DD).
            
        Returns:
            List of daily bar records.
        """
        logger.info(f"Fetching daily bars for {code} from {from_date} to {to_date}")
        
        params = {
            'code': code,
            'from': from_date,
            'to': to_date
        }
        
        return self._fetch_paginated('/v2/equities/bars/daily', params)
    
    def get_investor_types(
        self, 
        code: str, 
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch trading by investor type (Foreign/Retail/etc).
        
        Args:
            code: Stock code.
            from_date: Start date (optional).
            to_date: End date (optional).
            
        Returns:
            List of investor type records.
        """
        logger.info(f"Fetching investor type data for {code}")
        
        params = {'code': code}
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date
        
        try:
            return self._fetch_paginated('/v2/equities/investor-types', params)
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Investor data not available for {code}: {e}")
            return []
    
    def get_earnings_calendar(
        self, 
        code: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch earnings calendar.
        
        Args:
            code: Stock code (optional, for filtering).
            from_date: Start date (optional).
            to_date: End date (optional).
            
        Returns:
            List of earnings event records.
        """
        logger.info(f"Fetching earnings calendar{' for ' + code if code else ''}")
        
        params = {}
        if code:
            params['code'] = code
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date
        
        try:
            response = self._make_request('/v2/equities/earnings-calendar', params)
            return response.get('data', [])
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Earnings calendar not available: {e}")
            return []
    
    def get_topix_bars(
        self, 
        from_date: str, 
        to_date: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch TOPIX index daily bars.
        
        Args:
            from_date: Start date (YYYY-MM-DD).
            to_date: End date (YYYY-MM-DD).
            
        Returns:
            List of TOPIX bar records.
        """
        logger.info(f"Fetching TOPIX from {from_date} to {to_date}")
        
        params = {
            'from': from_date,
            'to': to_date
        }
        
        return self._fetch_paginated('/v2/indices/bars/daily/topix', params)
    
    def get_financial_summary(
        self, 
        code: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch financial summary (Sales, Operating Profit, etc).
        
        Args:
            code: Stock code.
            
        Returns:
            List of financial summary records.
        """
        logger.info(f"Fetching financial summary for {code}")
        
        params = {'code': code}
        
        try:
            response = self._make_request('/v2/fins/summary', params)
            return response.get('data', [])
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Financial summary not available for {code}: {e}")
            return []
