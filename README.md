# Advanced Web Crawler

## Overview

This project is a powerful, asynchronous web crawler built in Python, designed for large-scale, modern web application analysis. It leverages browser automation to discover API endpoints, detect dynamic content, and intelligently backtrack, providing deep insights into website structure and behavior.

---

## Features

- **Asynchronous Crawling:** Efficiently crawls thousands of pages using Python's `asyncio` and `aiohttp`.
- **Browser Automation:** Uses Playwright to render and interact with JavaScript-heavy, dynamic web pages.
- **API Endpoint Discovery:** Automatically detects REST and GraphQL API endpoints, capturing full request/response data.
- **Dynamic Content Detection:** Identifies pages using JavaScript frameworks and AJAX/XHR requests.
- **Intelligent Backtracking:** Skips and logs static resources, external domains, and non-relevant URLs with detailed reasoning.
- **Comprehensive Data Extraction:** Gathers links, forms, resources, meta tags, headings, and more from each page.
- **Breadth-First Crawling:** Uses a queue to ensure wide coverage of the target site.
- **Detailed Reporting:** Generates JSON reports with crawl summaries, content analysis, technology usage, API stats, and backtracking reasons.
- **Robust Logging:** Logs all activity to both console and file for easy debugging and audit.

---

## Architecture

### Core Data Structures

- **APIEndpoint:** Captures all details of API requests and responses, including headers, body, timing, and extracted fields.
- **PageInfo:** Stores metadata for each crawled page, such as title, status, resources, dynamic indicators, and relationships.
- **BacktrackEvent:** Logs every decision to skip a URL, with reasons and context for later analysis.

### Main Class: `AdvancedWebCrawler`

Manages the crawl state and orchestrates all crawling, extraction, and analysis tasks. Key attributes include:

- `visited_urls`: Set of URLs already processed.
- `pending_urls`: Queue for breadth-first crawling.
- `page_data`: Stores all extracted `PageInfo`.
- `api_endpoints`: All discovered API endpoints.
- `backtrack_events`: Log of all skipped URLs and reasons.

---

## Key Technologies

- **Python 3.8+**
- **Playwright** for browser automation
- **aiohttp** for asynchronous HTTP requests
- **asyncio** for concurrency
- **dataclasses** for structured data
- **logging** for robust, multi-target logs

---

## Usage

### Prerequisites

- Python 3.8 or higher
- Playwright and its browser binaries

Install dependencies:
```bash
pip install -r requirements.txt
python -m playwright install
```

### Running the Crawler

Edit the `main.py` file to set your `start_url` and desired parameters.

Run the crawler:
```bash
python main.py
```

### Output

- **JSON Report:** Crawl results are saved as a timestamped JSON file (e.g., `crawl_results_example_com_YYYYMMDD_HHMMSS.json`).
- **Console Summary:** Key statistics and findings are printed after the crawl.

---

## Customization

You can adjust the following parameters in `AdvancedWebCrawler`:

- `start_url`: The initial URL to crawl.
- `max_pages`: Maximum number of pages to crawl.
- `delay`: Delay between requests (seconds).
- `concurrent_requests`: Number of concurrent browser pages.
- `follow_external_links`: Whether to crawl external domains.
- `crawl_static_resources`: Whether to crawl static files (JS, CSS, images, etc.).

---

## Example Report Contents

- **Crawl Summary:** Total pages, max depth, duration.
- **Content Analysis:** Dynamic vs. static pages, resource counts.
- **API Analysis:** Number and types of API endpoints, methods used.
- **Backtracking Analysis:** Reasons for skipped URLs, external domains found.
- **Technology Analysis:** Detected JavaScript frameworks and dynamic features.
- **Performance Metrics:** Average, fastest, and slowest page response times.

---

## License

MIT License

---

## Acknowledgements

- [Playwright](https://playwright.dev/python/)
- [aiohttp](https://docs.aiohttp.org/)
- [Python asyncio](https://docs.python.org/3/library/asyncio.html)
