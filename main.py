import asyncio
import json
import time
import hashlib
import subprocess
import sys
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import aiohttp
from playwright.async_api import async_playwright, Page, BrowserContext
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crawler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class APIEndpoint:
    url: str
    method: str
    request_headers: Dict[str, str]
    request_body: Optional[str]
    request_params: Dict[str, str]
    response_status: int
    response_headers: Dict[str, str]
    response_body: Optional[str]
    response_size: int
    response_time: float
    content_type: str
    discovered_on_page: str
    timestamp: str
    is_api: bool
    api_type: str
    fields_extracted: Dict[str, Any]

@dataclass
class BacktrackEvent:
    url: str
    reason: str
    timestamp: str
    parent_url: Optional[str]
    depth: int
    resource_type: str = ""
    external_domain: str = ""

@dataclass
class PageInfo:
    url: str
    title: str
    status_code: int
    response_time: float
    content_length: int
    content_type: str
    is_dynamic: bool
    dynamic_indicators: List[str]
    links: List[str]
    forms: List[Dict]
    javascript_files: List[str]
    css_files: List[str]
    images: List[str]
    meta_tags: Dict[str, str]
    headings: Dict[str, List[str]]
    text_content_hash: str
    discovered_at: str
    depth: int
    api_endpoints: List[APIEndpoint]
    parent_url: Optional[str] = None
    backtrack_events: List[BacktrackEvent] = None

    def __post_init__(self):
        if self.backtrack_events is None:
            self.backtrack_events = []

class AdvancedWebCrawler:
    def __init__(self, start_url: str, max_pages: int = 10000, 
                 delay: float = 1.0, concurrent_requests: int = 5, 
                 follow_external_links: bool = False, crawl_static_resources: bool = False):
        self.start_url = start_url
        self.base_domain = urlparse(start_url).netloc
        self.max_pages = max_pages
        self.delay = delay
        self.concurrent_requests = concurrent_requests
        self.follow_external_links = follow_external_links
        self.crawl_static_resources = crawl_static_resources
        self.visited_urls: Set[str] = set()
        self.pending_urls: deque = deque([(start_url, 0, None)])
        self.page_data: Dict[str, PageInfo] = {}
        self.api_endpoints: Dict[str, APIEndpoint] = {}
        self.url_patterns: Dict[str, List[str]] = defaultdict(list)
        self.dynamic_pages: Set[str] = set()
        self.static_pages: Set[str] = set()
        self.backtrack_events: List[BacktrackEvent] = []
        self.external_domains: Set[str] = set()
        self.skipped_resources: Dict[str, List[str]] = defaultdict(list)
        self.discovered_js_files: Set[str] = set()
        self.discovered_css_files: Set[str] = set()
        self.discovered_images: Set[str] = set()
        self.api_methods: Dict[str, int] = defaultdict(int)
        self.api_patterns: Dict[str, List[str]] = defaultdict(list)
        self.graphql_endpoints: Set[str] = set()
        self.rest_endpoints: Set[str] = set()
        self.browser = None
        self.context = None
        
    async def initialize_browser(self):
        """Initialize Playwright browser with auto-install"""
        try:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
        except Exception as e:
            if "Executable doesn't exist" in str(e):
                logger.info("Playwright browsers not found. Installing...")
                try:
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], 
                                 check=True, capture_output=True, text=True)
                    logger.info("Playwright browsers installed successfully")
                    
                    playwright = await async_playwright().start()
                    self.browser = await playwright.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-dev-shm-usage']
                    )
                    self.context = await self.browser.new_context(
                        viewport={'width': 1920, 'height': 1080},
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    )
                except subprocess.CalledProcessError as install_error:
                    logger.error(f"Failed to install Playwright browsers: {install_error}")
                    raise
            else:
                logger.error(f"Failed to initialize browser: {e}")
                raise
        
    async def close_browser(self):
        """Close browser resources"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
    
    def create_backtrack_event(self, url: str, reason: str, parent_url: Optional[str] = None, 
                             depth: int = 0, resource_type: str = "", external_domain: str = "") -> BacktrackEvent:
        """Create a backtrack event for logging purposes"""
        event = BacktrackEvent(
            url=url,
            reason=reason,
            timestamp=datetime.now().isoformat(),
            parent_url=parent_url,
            depth=depth,
            resource_type=resource_type,
            external_domain=external_domain
        )
        self.backtrack_events.append(event)
        return event
    
    def should_backtrack(self, url: str, parent_url: Optional[str] = None, depth: int = 0) -> Tuple[bool, str]:
        """Determine if we should backtrack from this URL and why"""
        parsed = urlparse(url)
        
        # Check if it's an external domain
        if parsed.netloc != self.base_domain:
            if not self.follow_external_links:
                self.external_domains.add(parsed.netloc)
                return True, f"External domain: {parsed.netloc}"
        
        # Check if it's a static resource
        static_extensions = {'.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', 
                           '.ico', '.woff', '.woff2', '.ttf', '.eot', '.pdf', '.zip', 
                           '.rar', '.tar', '.gz', '.mp4', '.mp3', '.avi', '.mov'}
        
        path_lower = parsed.path.lower()
        for ext in static_extensions:
            if path_lower.endswith(ext):
                if not self.crawl_static_resources:
                    # Track the resource type
                    if ext in {'.js'}:
                        self.discovered_js_files.add(url)
                        resource_type = "JavaScript"
                    elif ext in {'.css'}:
                        self.discovered_css_files.add(url)
                        resource_type = "CSS"
                    elif ext in {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'}:
                        self.discovered_images.add(url)
                        resource_type = "Image"
                    else:
                        resource_type = "Static Resource"
                    
                    return True, f"Static resource ({resource_type}): {ext}"
        
        # Check for common API endpoints that we might want to skip
        api_patterns = ['/api/', '/graphql', '/rest/', '/v1/', '/v2/']
        for pattern in api_patterns:
            if pattern in url.lower():
                # Don't backtrack from API endpoints, but log them
                logger.debug(f"API endpoint detected: {url}")
                break
        
        return False, ""
    
    def normalize_url(self, url: str, base_url: str) -> str:
        """Normalize and resolve relative URLs"""
        if not url:
            return ""
        
        # Handle relative URLs
        full_url = urljoin(base_url, url)
        parsed = urlparse(full_url)
        
        # Remove fragments
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
            
        return normalized
    
    def is_same_domain(self, url: str) -> bool:
        """Check if URL belongs to the same domain"""
        return urlparse(url).netloc == self.base_domain
    
    def should_crawl_url(self, url: str, parent_url: Optional[str] = None, depth: int = 0) -> bool:
        """Determine if URL should be crawled"""
        if not url or url in self.visited_urls:
            return False
        
        # Prevent crawling external domains
        if not self.is_same_domain(url):
            self.create_backtrack_event(
                url=url,
                reason="External domain (not allowed)",
                parent_url=parent_url,
                depth=depth
            )
            logger.debug(f"Skipping {url}: External domain (not allowed)")
            return False
        
        # Check if we should backtrack
        should_backtrack, reason = self.should_backtrack(url, parent_url, depth)
        if should_backtrack:
            # Create backtrack event
            parsed = urlparse(url)
            external_domain = parsed.netloc if parsed.netloc != self.base_domain else ""
            resource_type = reason.split('(')[1].split(')')[0] if '(' in reason else ""
            
            self.create_backtrack_event(
                url=url,
                reason=reason,
                parent_url=parent_url,
                depth=depth,
                resource_type=resource_type,
                external_domain=external_domain
            )
            
            # Add to appropriate tracking list
            self.skipped_resources[reason].append(url)
            
            logger.debug(f"Backtracking from {url}: {reason}")
            return False
        
        # Remove depth limit check
        return True
    
    async def setup_network_monitoring(self, page: Page, url: str) -> List[APIEndpoint]:
        """Setup network monitoring to capture API endpoints"""
        api_endpoints = []
        
        def handle_response(response):
            """Handle each network response to complete API endpoint data"""
            try:
                request = response.request
                request_url = request.url
                method = request.method
                
                # Skip non-API requests
                if not self.is_api_request(request_url, method):
                    return
                    
                # Find the corresponding request in our endpoints
                for endpoint in api_endpoints:
                    if endpoint.url == request_url and endpoint.method == method:
                        # Update with response data
                        endpoint.response_status = response.status
                        endpoint.response_headers = dict(response.headers)
                        endpoint.response_size = len(response.body()) if hasattr(response, 'body') else 0
                        endpoint.content_type = response.headers.get('content-type', '')
                        endpoint.response_time = time.time() - endpoint.response_time  # assuming we stored start time
                        
                        # Try to get response body
                        try:
                            endpoint.response_body = response.text()
                        except:
                            endpoint.response_body = None
                        
                        # Extract fields from response
                        endpoint.fields_extracted = self.extract_api_fields(endpoint.response_body, endpoint.content_type)
                        
                        # Classify API endpoints
                        if endpoint.api_type == 'GraphQL':
                            self.graphql_endpoints.add(request_url)
                        elif endpoint.api_type == 'REST':
                            self.rest_endpoints.add(request_url)
                        
                        # Track API methods
                        self.api_methods[method] += 1
                        
                        # Store endpoint
                        endpoint_key = f"{method}:{request_url}"
                        self.api_endpoints[endpoint_key] = endpoint
                        
                        break
                        
            except Exception as e:
                logger.debug(f"Error processing response for {response.url}: {e}")
        
        def handle_request(request):
            """Handle each network request to identify API endpoints"""
            try:
                request_url = request.url
                method = request.method
                
                # Skip non-API requests
                if not self.is_api_request(request_url, method):
                    return
                    
                # Create API endpoint data structure
                endpoint = APIEndpoint(
                    url=request_url,
                    method=method,
                    request_headers=dict(request.headers),
                    request_body=request.post_data,
                    request_params=dict(parse_qs(urlparse(request_url).query)),
                    response_status=0,
                    response_headers={},
                    response_body=None,
                    response_size=0,
                    response_time=time.time(),  # Store start time
                    content_type="",
                    discovered_on_page=url,
                    timestamp=datetime.now().isoformat(),
                    is_api=True,
                    api_type=self.detect_api_type(request_url, method, request.post_data),
                    fields_extracted={}
                )
                
                api_endpoints.append(endpoint)
                
                # Track API patterns
                parsed_url = urlparse(request_url)
                path_pattern = parsed_url.path
                self.api_patterns[endpoint.api_type].append(path_pattern)
                
            except Exception as e:
                logger.debug(f"Error processing request {request.url}: {e}")
        
        # Setup request and response handlers
        page.on('request', handle_request)
        page.on('response', handle_response)
        
        return api_endpoints


    def extract_api_fields(self, response_body: Optional[str], content_type: str) -> Dict[str, Any]:
        """Extract fields from API response"""
        fields = {}
        
        if not response_body:
            return fields
        
        try:
            if 'json' in content_type.lower():
                import json
                data = json.loads(response_body)
                
                # Extract top-level keys
                if isinstance(data, dict):
                    fields['response_keys'] = list(data.keys())
                    fields['response_structure'] = self.analyze_json_structure(data)
                elif isinstance(data, list) and data:
                    fields['response_type'] = 'array'
                    fields['array_length'] = len(data)
                    if isinstance(data[0], dict):
                        fields['item_keys'] = list(data[0].keys())
                        
            elif 'xml' in content_type.lower():
                # Basic XML parsing
                import re
                tags = re.findall(r'<(\w+)[^>]*>', response_body)
                fields['xml_tags'] = list(set(tags))
                
        except Exception as e:
            logger.debug(f"Error extracting API fields: {e}")
            fields['extraction_error'] = str(e)
        
        return fields


    def analyze_json_structure(self, data: Any, max_depth: int = 3, current_depth: int = 0) -> Dict[str, Any]:
        """Analyze JSON structure recursively"""
        if current_depth >= max_depth:
            return {'max_depth_reached': True}
        
        if isinstance(data, dict):
            structure = {}
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    structure[key] = {
                        'type': type(value).__name__,
                        'structure': self.analyze_json_structure(value, max_depth, current_depth + 1)
                    }
                else:
                    structure[key] = {
                        'type': type(value).__name__,
                        'sample_value': str(value)[:100] if value else None
                    }
            return structure
        
        elif isinstance(data, list):
            if not data:
                return {'type': 'empty_array'}
            
            # Analyze first few items
            sample_items = data[:3]
            item_structures = []
            
            for item in sample_items:
                item_structures.append(self.analyze_json_structure(item, max_depth, current_depth + 1))
            
            return {
                'type': 'array',
                'length': len(data),
                'sample_structures': item_structures
            }
        
        else:
            return {
                'type': type(data).__name__,
                'sample_value': str(data)[:100] if data else None
            }



    def is_api_request(self, url: str, method: str) -> bool:
        """Determine if a request is likely an API call"""
        # Skip common static files
        static_extensions = {'.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2'}
        if any(url.endswith(ext) for ext in static_extensions):
            return False
            
        # Common API path patterns
        api_patterns = {'/api/', '/graphql', '/rest/', '/v1/', '/v2/', '/json', '/xml'}
        if any(pattern in url for pattern in api_patterns):
            return True
            
        # Check if URL looks like an API endpoint
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # Check for common API patterns
        if (method in {'POST', 'PUT', 'PATCH', 'DELETE'} or 
            path.startswith('/api') or 
            path.endswith('.json') or 
            path.endswith('.xml')):
            return True
            
        return False

    def detect_api_type(self, url: str, method: str, body: Optional[str]) -> str:
        """Detect the type of API (REST, GraphQL, etc.)"""
        if '/graphql' in url.lower():
            return 'GraphQL'
            
        if body and 'query' in body.lower() and ('{' in body and '}' in body):
            return 'GraphQL'
            
        if '/rest/' in url.lower() or '/api/' in url.lower():
            return 'REST'
            
        if method in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
            return 'REST'
            
        return 'Unknown'

    async def detect_dynamic_content(self, page: Page, url: str) -> Tuple[bool, List[str]]:
        """Detect if page has dynamic content"""
        indicators = []
        
        try:
            # Check for JavaScript frameworks
            js_frameworks = [
                'React', 'Angular', 'Vue', 'jQuery', 'Backbone', 'Ember',
                'Knockout', 'Svelte', 'Preact', 'Alpine'
            ]
            
            for framework in js_frameworks:
                if await page.evaluate(f'typeof {framework} !== "undefined"'):
                    indicators.append(f'JavaScript Framework: {framework}')
            
            # Check for AJAX/XHR requests
            xhr_count = await page.evaluate('''
                () => {
                    let count = 0;
                    const originalXHR = window.XMLHttpRequest;
                    window.XMLHttpRequest = function() {
                        count++;
                        return new originalXHR();
                    };
                    return count;
                }
            ''')
            
            if xhr_count > 0:
                indicators.append('AJAX/XHR Requests detected')
            
            # Check for DOM manipulation
            script_tags = await page.query_selector_all('script[src]')
            js_files = []
            for script in script_tags:
                src = await script.get_attribute('src')
                if src:
                    js_files.append(src)
            
            if js_files:
                indicators.append(f'External JavaScript files: {len(js_files)}')
            
            # Check for dynamic content indicators
            dynamic_selectors = [
                '[data-react-root]', '[ng-app]', '[v-app]', '.vue-app',
                '[data-vue-root]', '[data-angular-root]'
            ]
            
            for selector in dynamic_selectors:
                if await page.query_selector(selector):
                    indicators.append(f'Dynamic content selector: {selector}')
            
            # Check for WebSocket connections
            websocket_check = await page.evaluate('''
                () => typeof WebSocket !== "undefined" && WebSocket.prototype.send
            ''')
            
            if websocket_check:
                indicators.append('WebSocket support detected')
            
            # Wait for potential dynamic content to load
            await page.wait_for_timeout(2000)
            
            # Take two snapshots to compare
            initial_content = await page.content()
            await page.wait_for_timeout(1000)
            final_content = await page.content()
            
            if initial_content != final_content:
                indicators.append('Content changed after page load')
            
        except Exception as e:
            logger.warning(f"Error detecting dynamic content for {url}: {str(e)}")
        
        return len(indicators) > 0, indicators
    
    async def extract_page_data(self, page: Page, url: str, depth: int, parent_url: str) -> PageInfo:
        """Extract comprehensive page data including API endpoints"""
        start_time = time.time()
        
        try:
            # Set up network monitoring BEFORE any page interactions
            api_endpoints = await self.setup_network_monitoring(page, url)
            
            # Wait for page to load
            await page.wait_for_load_state('networkidle', timeout=30000)
            
            # Basic page info
            title = await page.title()
            content = await page.content()
            content_length = len(content)
            
            # Check if page is dynamic
            is_dynamic, dynamic_indicators = await self.detect_dynamic_content(page, url)
            
            # Interact with page to trigger API calls
            await self.trigger_page_interactions(page)
            
            # Extract links with backtracking
            links = []
            link_elements = await page.query_selector_all('a[href]')
            for link in link_elements:
                href = await link.get_attribute('href')
                if href:
                    normalized_url = self.normalize_url(href, url)
                    if normalized_url:
                        if self.should_crawl_url(normalized_url, url, depth + 1):
                            links.append(normalized_url)
            
            # Extract forms
            forms = []
            form_elements = await page.query_selector_all('form')
            for form in form_elements:
                action = await form.get_attribute('action') or ""
                method = await form.get_attribute('method') or "GET"
                
                # Get form inputs
                inputs = []
                input_elements = await form.query_selector_all('input, select, textarea')
                for inp in input_elements:
                    input_type = await inp.get_attribute('type') or 'text'
                    name = await inp.get_attribute('name') or ''
                    inputs.append({'type': input_type, 'name': name})
                
                forms.append({
                    'action': action,
                    'method': method.upper(),
                    'inputs': inputs
                })
            
            # Extract resources with backtracking
            js_files = []
            css_files = []
            images = []
            
            # JavaScript files
            script_elements = await page.query_selector_all('script[src]')
            for script in script_elements:
                src = await script.get_attribute('src')
                if src:
                    normalized_src = self.normalize_url(src, url)
                    js_files.append(normalized_src)
                    # Track but don't crawl
                    self.discovered_js_files.add(normalized_src)
            
            # CSS files
            link_elements = await page.query_selector_all('link[rel="stylesheet"]')
            for link in link_elements:
                href = await link.get_attribute('href')
                if href:
                    normalized_href = self.normalize_url(href, url)
                    css_files.append(normalized_href)
                    # Track but don't crawl
                    self.discovered_css_files.add(normalized_href)
            
            # Images
            img_elements = await page.query_selector_all('img[src]')
            for img in img_elements:
                src = await img.get_attribute('src')
                if src:
                    normalized_src = self.normalize_url(src, url)
                    images.append(normalized_src)
                    # Track but don't crawl
                    self.discovered_images.add(normalized_src)
            
            # Extract meta tags
            meta_tags = {}
            meta_elements = await page.query_selector_all('meta')
            for meta in meta_elements:
                name = await meta.get_attribute('name')
                property_attr = await meta.get_attribute('property')
                content = await meta.get_attribute('content')
                
                if name and content:
                    meta_tags[name] = content
                elif property_attr and content:
                    meta_tags[property_attr] = content
            
            # Extract headings
            headings = {}
            for i in range(1, 7):
                h_elements = await page.query_selector_all(f'h{i}')
                h_texts = []
                for h in h_elements:
                    text = await h.text_content()
                    if text:
                        h_texts.append(text.strip())
                if h_texts:
                    headings[f'h{i}'] = h_texts
            
            # Create text content hash
            text_content = await page.evaluate('''
                () => document.body.innerText || document.body.textContent || ''
            ''')
            content_hash = hashlib.md5(text_content.encode()).hexdigest()
            
            response_time = time.time() - start_time
            
            return PageInfo(
                url=url,
                title=title,
                status_code=200,
                response_time=response_time,
                content_length=content_length,
                content_type="text/html",
                is_dynamic=is_dynamic,
                dynamic_indicators=dynamic_indicators,
                links=links,
                forms=forms,
                javascript_files=js_files,
                css_files=css_files,
                images=images,
                meta_tags=meta_tags,
                headings=headings,
                text_content_hash=content_hash,
                discovered_at=datetime.now().isoformat(),
                depth=depth,
                api_endpoints=api_endpoints,
                parent_url=parent_url,
                backtrack_events=[]
            )
            
        except Exception as e:
            logger.error(f"Error extracting data from {url}: {str(e)}")
            return PageInfo(
                url=url,
                title="Error",
                status_code=500,
                response_time=time.time() - start_time,
                content_length=0,
                content_type="error",
                is_dynamic=False,
                dynamic_indicators=[f"Error: {str(e)}"],
                links=[],
                forms=[],
                javascript_files=[],
                css_files=[],
                images=[],
                meta_tags={},
                headings={},
                text_content_hash="",
                discovered_at=datetime.now().isoformat(),
                depth=depth,
                api_endpoints=[],
                parent_url=parent_url,
                backtrack_events=[]
            )
    
    async def trigger_page_interactions(self, page: Page):
        """Trigger interactions to discover API endpoints"""
        try:
            # Scroll to trigger lazy loading
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(1000)
            
            # Click on buttons and links that might trigger API calls
            clickable_elements = await page.query_selector_all('button, [role="button"], .btn, input[type="submit"]')
            
            for element in clickable_elements[:5]:  # Limit to first 5 to avoid too many interactions
                try:
                    # Check if element is visible
                    is_visible = await element.is_visible()
                    if is_visible:
                        await element.click()
                        await page.wait_for_timeout(500)  # Wait for potential API calls
                except Exception as e:
                    logger.debug(f"Could not click element: {e}")
            
            # Try to trigger form submissions (but don't actually submit)
            forms = await page.query_selector_all('form')
            for form in forms[:3]:  # Limit to first 3 forms
                try:
                    # Focus on first input to trigger any validation APIs
                    first_input = await form.query_selector('input, select, textarea')
                    if first_input:
                        await first_input.focus()
                        await page.wait_for_timeout(300)
                except Exception as e:
                    logger.debug(f"Could not interact with form: {e}")
            
            # Wait for any delayed API calls
            await page.wait_for_timeout(2000)
            
        except Exception as e:
            logger.debug(f"Error during page interactions: {e}")

    async def crawl_page(self, url: str, depth: int, parent_url: str) -> Optional[PageInfo]:
        """Crawl a single page"""
        if url in self.visited_urls:
            return None
        
        # Remove depth limit check
        self.visited_urls.add(url)
        logger.info(f"Crawling: {url} (depth: {depth})")
        
        try:
            page = await self.context.new_page()
            
            # Navigate to page
            response = await page.goto(url, timeout=30000, wait_until='networkidle')
            
            if not response or response.status >= 400:
                logger.warning(f"Failed to load {url}: Status {response.status if response else 'No response'}")
                await page.close()
                return None
            
            # Extract page data
            page_info = await self.extract_page_data(page, url, depth, parent_url)
            
            # Add discovered links to pending queue
            for link in page_info.links:
                if link not in self.visited_urls and len(self.pending_urls) < self.max_pages:
                    self.pending_urls.append((link, depth + 1, url))
            
            # Classify page
            if page_info.is_dynamic:
                self.dynamic_pages.add(url)
            else:
                self.static_pages.add(url)
            
            # Store page data
            self.page_data[url] = page_info
            
            await page.close()
            await asyncio.sleep(self.delay)
            
            return page_info
            
        except Exception as e:
            logger.error(f"Error crawling {url}: {str(e)}")
            return None
    
    async def run_crawler(self):
        """Run the main crawler"""
        logger.info(f"Starting crawler for {self.start_url}")
        # Remove depth limit log
        await self.initialize_browser()
        
        try:
            semaphore = asyncio.Semaphore(self.concurrent_requests)
            
            async def crawl_with_semaphore(url_data):
                async with semaphore:
                    url, depth, parent = url_data
                    return await self.crawl_page(url, depth, parent)
            
            while self.pending_urls and len(self.visited_urls) < self.max_pages:
                # Get next batch of URLs
                batch_size = min(self.concurrent_requests, len(self.pending_urls))
                batch = [self.pending_urls.popleft() for _ in range(batch_size)]
                
                # Process batch
                tasks = [crawl_with_semaphore(url_data) for url_data in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Log progress
                logger.info(f"Processed batch. Visited: {len(self.visited_urls)}, "
                           f"Pending: {len(self.pending_urls)}, "
                           f"Dynamic: {len(self.dynamic_pages)}, "
                           f"Static: {len(self.static_pages)}, "
                           f"Backtrack events: {len(self.backtrack_events)}")
        
        finally:
            await self.close_browser()
    
    def generate_report(self) -> Dict:
        """Generate comprehensive crawl report including backtracking analysis"""
        total_pages = len(self.page_data)
        
        # Analyze URL patterns
        url_analysis = defaultdict(int)
        for url in self.visited_urls:
            parsed = urlparse(url)
            path_parts = [part for part in parsed.path.split('/') if part]
            
            if not path_parts:
                url_analysis['root'] += 1
            else:
                url_analysis[path_parts[0]] += 1
        
        # Analyze content types
        content_analysis = {
            'total_pages': total_pages,
            'dynamic_pages': len(self.dynamic_pages),
            'static_pages': len(self.static_pages),
            'dynamic_percentage': (len(self.dynamic_pages) / total_pages * 100) if total_pages > 0 else 0,
            'static_percentage': (len(self.static_pages) / total_pages * 100) if total_pages > 0 else 0
        }
        
        # Backtracking analysis
        backtrack_analysis = {
            'total_backtrack_events': len(self.backtrack_events),
            'external_domains_found': len(self.external_domains),
            'external_domains_list': list(self.external_domains),
            'javascript_files_found': len(self.discovered_js_files),
            'css_files_found': len(self.discovered_css_files),
            'images_found': len(self.discovered_images),
            'backtrack_reasons': defaultdict(int),
            'skipped_resources_summary': {k: len(v) for k, v in self.skipped_resources.items()}
        }
        
        # Count backtrack reasons
        for event in self.backtrack_events:
            backtrack_analysis['backtrack_reasons'][event.reason] += 1
        
        # Technology analysis
        tech_analysis = defaultdict(int)
        for page_info in self.page_data.values():
            for indicator in page_info.dynamic_indicators:
                tech_analysis[indicator] += 1
        
        # API analysis
        api_analysis = {
            'total_api_endpoints': len(self.api_endpoints),
            'graphql_endpoints': len(self.graphql_endpoints),
            'rest_endpoints': len(self.rest_endpoints),
            'api_methods': dict(self.api_methods),
            'api_patterns': dict(self.api_patterns)
        }
        
        # Performance analysis
        response_times = [p.response_time for p in self.page_data.values()]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        return {
            'crawl_summary': {
                'start_url': self.start_url,
                'total_pages_crawled': total_pages,
                'max_depth_reached': max(p.depth for p in self.page_data.values()) if self.page_data else 0,
                'crawl_duration': datetime.now().isoformat(),
            },
            'content_analysis': content_analysis,
            'backtrack_analysis': backtrack_analysis,
            'url_patterns': dict(url_analysis),
            'technology_analysis': dict(tech_analysis),
            'api_analysis': api_analysis,
            'performance_metrics': {
                'average_response_time': avg_response_time,
                'fastest_page': min(response_times) if response_times else 0,
                'slowest_page': max(response_times) if response_times else 0,
            },
            'dynamic_pages_list': list(self.dynamic_pages),
            'static_pages_list': list(self.static_pages),
            'backtrack_events': [asdict(event) for event in self.backtrack_events],
            'all_pages_data': {url: asdict(info) for url, info in self.page_data.items()}
        }
        
    def save_results(self, filename: str = None):
        """Save crawl results to JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            domain = self.base_domain.replace('.', '_')
            filename = f"crawl_results_{domain}_{timestamp}.json"
            
        report = self.generate_report()
            
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Results saved to {filename}")
        return filename    

# Usage example and setup verification
def verify_setup():
    """Verify all required packages are installed"""
    required_packages = ['playwright', 'aiohttp']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"Missing packages: {missing_packages}")
        print("Install with: pip install " + " ".join(missing_packages))
        return False
    
    return True

async def main():
    # Verify setup
    if not verify_setup():
        return
    
    print("Starting Advanced Web Crawler...")
    print("=" * 60)
    
    # Initialize crawler
    crawler = AdvancedWebCrawler(
        start_url="https://ginandjuice.shop/",
        # max_depth=3,  # Remove max_depth
        max_pages=100000,
        delay=1.0,
        concurrent_requests=3
    )
    
    try:
        # Run crawler
        await crawler.run_crawler()
        
        # Save results
        results_file = crawler.save_results()
        
        # Generate summary report
        report = crawler.generate_report()
        
        print("\n" + "="*60)
        print("CRAWL SUMMARY")
        print("="*60)
        print(f"Total pages crawled: {report['content_analysis']['total_pages']}")
        print(f"Dynamic pages: {report['content_analysis']['dynamic_pages']} ({report['content_analysis']['dynamic_percentage']:.1f}%)")
        print(f"Static pages: {report['content_analysis']['static_pages']} ({report['content_analysis']['static_percentage']:.1f}%)")
        print(f"Average response time: {report['performance_metrics']['average_response_time']:.2f}s")


        print(f"\nBacktracking Analysis:")
        print(f"Total backtrack events: {report['backtrack_analysis']['total_backtrack_events']}")
        print(f"External domains found: {report['backtrack_analysis']['external_domains_found']}")
        print(f"JavaScript files found: {report['backtrack_analysis']['javascript_files_found']}")
        print(f"CSS files found: {report['backtrack_analysis']['css_files_found']}")
        print(f"Images found: {report['backtrack_analysis']['images_found']}")

        print(f"\nAPI Analysis:")
        print(f"Total API endpoints: {report['api_analysis']['total_api_endpoints']}")
        print(f"GraphQL endpoints: {report['api_analysis']['graphql_endpoints']}")
        print(f"REST endpoints: {report['api_analysis']['rest_endpoints']}")

        print(f"\nResults saved to: {results_file}")

        print("\nURL Patterns:")
        for pattern, count in report['url_patterns'].items():
            print(f"  {pattern}: {count}")

        print("\nTechnology Analysis:")
        for tech, count in report['technology_analysis'].items():
            print(f"  {tech}: {count}")

        print("\nBacktrack Reasons:")
        for reason, count in report['backtrack_analysis']['backtrack_reasons'].items():
            print(f"  {reason}: {count}")

        if report['backtrack_analysis']['external_domains_list']:
            print(f"\nExternal Domains Found:")
            for domain in report['backtrack_analysis']['external_domains_list'][:10]:
                print(f"  - {domain}")

        # Show some dynamic pages found
        if report['dynamic_pages_list']:
            print(f"\nDynamic Pages Found ({len(report['dynamic_pages_list'])}):")
            for page in report['dynamic_pages_list'][:5]:  # Show first 5
                print(f"  - {page}")
            if len(report['dynamic_pages_list']) > 5:
                print(f"  ... and {len(report['dynamic_pages_list']) - 5} more")

        # Show some static pages found
        if report['static_pages_list']:
            print(f"\nStatic Pages Found ({len(report['static_pages_list'])}):")
            for page in report['static_pages_list'][:5]:  # Show first 5
                print(f"  - {page}")
            if len(report['static_pages_list']) > 5:
                print(f"  ... and {len(report['static_pages_list']) - 5} more")
                                
    except KeyboardInterrupt:
        print("\nCrawling interrupted by user")
        logger.info("Crawling interrupted by user")
        
        # Save partial results
        if crawler.page_data:
            results_file = crawler.save_results()
            print(f"Partial results saved to: {results_file}")
            
    except Exception as e:
        print(f"Error during crawling: {e}")
        logger.error(f"Error during crawling: {e}")
        
        # Save partial results if any
        if crawler.page_data:
            results_file = crawler.save_results()
            print(f"Partial results saved to: {results_file}")

if __name__ == "__main__":
    asyncio.run(main())
