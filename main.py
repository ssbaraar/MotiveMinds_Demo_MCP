import os
import logging
import urllib.request
import urllib.parse
import urllib.error
import base64
import ssl
import json
from typing import Optional, Dict

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ---------- env & logging ----------
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MotivemindsMCP")

# ---------- SSL (sandbox only) ----------
ssl_context = ssl._create_unverified_context()

# ---------- MCP server ----------
mcp = FastMCP(
    "MotivemindsMCPServer",
    stateless_http=True,
    log_level="INFO",
)

# ---------- SAP config ----------
SAP_HOST      = os.getenv("SAP_HOST")              # e.g. "https://sap.example.com"
SAP_PORT      = os.getenv("SAP_PORT", "443")
SAP_CLIENT    = os.getenv("SAP_CLIENT", "100")
AUTH_USERNAME = os.getenv("AUTH_USERNAME")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD")

SAP_SERVICES = {
    "business_partner": "sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Customer",
    "product_description": "/sap/opu/odata4/sap/api_product/srvd_a2x/sap/product/0001/ProductDescription",
    "sales_order": "sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder",
}

def get_sap_base_url(service_path: str) -> str:
    if not SAP_HOST:
        raise ValueError("SAP_HOST must be set (e.g. https://<host>).")
    if not SAP_CLIENT:
        raise ValueError("SAP_CLIENT must be set (e.g. 100).")
    sp = (service_path or "").lstrip("/")
    return f"{SAP_HOST}:{SAP_PORT}/{sp}?sap-client={SAP_CLIENT}"

def _auth(req: urllib.request.Request) -> None:
    if AUTH_USERNAME and AUTH_PASSWORD:
        creds = f"{AUTH_USERNAME}:{AUTH_PASSWORD}"
        token = base64.b64encode(creds.encode()).decode()
        req.add_header("Authorization", f"Basic {token}")

# ---------- TOOLS ----------

@mcp.tool()
def searchCustomerByCustomerDescription(
    description: str,
    search_field: str = "CustomerName",
    exact_match: bool = False,
    max_results: int = 10,
    base_url: Optional[str] = None,
) -> str:
    """Search customer numbers by description using SAP Business Partner API (OData v2)."""
    try:
        base = base_url or get_sap_base_url(SAP_SERVICES["business_partner"])
        filter_query = (
            f"{search_field} eq '{description}'"
            if exact_match else
            f"substringof('{description}', {search_field}) eq true"
        )
        params = {"$filter": filter_query, "$select": "Customer,CustomerName,CustomerFullName", "$top": max_results}
        url = f"{base}&{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"

        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/json")
        _auth(req)

        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        if "d" in payload and "results" in payload["d"]:
            customers = payload["d"]["results"]
            return json.dumps({
                "search_query": description,
                "search_field": search_field,
                "exact_match": exact_match,
                "found_customers": len(customers),
                "customers": [
                    {
                        "Customer": c.get("Customer", ""),
                        "CustomerName": c.get("CustomerName", ""),
                        "CustomerFullName": c.get("CustomerFullName", ""),
                    } for c in customers
                ],
            }, indent=2)

        return f"No customers found matching: '{description}'"
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8") if e.fp else "No error details"
        return f"HTTP Error {e.code}: {e.reason}\nDetails: {details}"
    except Exception as e:
        return f"API call failed: {str(e)}"

@mcp.tool()
def searchProductByDescription(
    description: Optional[str] = None,
    search_field: str = "ProductDescription",
    language: str = "EN",
    exact_match: bool = False,
    max_results: int = 10,
    product: Optional[str] = None,
    key_mode: str = "auto",          # 'segment' | 'paren' | 'auto'
    service_version: str = "0002",
    base_url: Optional[str] = None,
) -> str:
    """Search (OData v4) or fetch a single ProductDescription by keys."""
    try:
        def get_service_base_path(version: str) -> str:
            return f"/sap/opu/odata4/sap/api_product/srvd_a2x/sap/product/{version}/ProductDescription"

        def append_query(url: str, params: dict) -> str:
            qp = {k: v for k, v in params.items() if v is not None}
            if not qp: return url
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}{urllib.parse.urlencode(qp, quote_via=urllib.parse.quote)}"

        def build_base_url() -> str:
            sp = get_service_base_path(service_version)
            return base_url or get_sap_base_url(sp)

        def make_request(url: str):
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")
            req.add_header("Content-Type", "application/json")
            _auth(req)
            return urllib.request.urlopen(req, timeout=30, context=ssl_context)

        base = build_base_url()

        if product:
            candidates = []
            if key_mode in ("segment", "auto"):
                seg = base.rstrip("/") + "/" + urllib.parse.quote(product, safe="") + "/" + urllib.parse.quote(language, safe="")
                seg = append_query(seg, {"$select": "Product,ProductDescription,Language"})
                candidates.append(("segment", seg))
            if key_mode in ("paren", "auto"):
                paren = base.rstrip("/") + f"(Product='{product}',Language='{language}')"
                paren = append_query(paren, {"$select": "Product,ProductDescription,Language"})
                candidates.append(("paren", paren))

            last_err = None
            for mode, url in candidates:
                try:
                    with make_request(url) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                        if isinstance(body, dict) and "Product" in body:
                            items = [body]
                        elif isinstance(body, dict) and "value" in body:
                            items = body["value"] if isinstance(body["value"], list) else [body["value"]]
                        else:
                            items = []
                        result = {
                            "mode": f"key_{mode}",
                            "product_key": product,
                            "language": language,
                            "found_products": len(items),
                            "products": [
                                {
                                    "Product": p.get("Product", ""),
                                    "ProductDescription": p.get("ProductDescription", ""),
                                    "Language": p.get("Language", ""),
                                } for p in items
                            ],
                        }
                        return json.dumps(result, indent=2) if items else json.dumps(
                            {"message": f"No ProductDescription found for {product}/{language}", **result}, indent=2
                        )
                except urllib.error.HTTPError as e:
                    last_err = f"HTTP Error {e.code}: {e.reason}\nURL: {url}\nDetails: {(e.read().decode('utf-8') if e.fp else 'No details')}"
                    if key_mode != "auto" or e.code not in (400, 404):
                        return last_err
                except Exception as e:
                    last_err = f"API call failed: {str(e)}"
                    if key_mode != "auto":
                        return last_err
            return last_err or f"ProductDescription not found for {product}/{language}"

        if not description:
            return "Provide either 'description' (search) or 'product' (direct key)."

        filter_query = (
            f"{search_field} eq '{description}' and Language eq '{language}'"
            if exact_match else
            f"contains({search_field}, '{description}') and Language eq '{language}'"
        )
        url = append_query(base, {"$filter": filter_query, "$select": "Product,ProductDescription,Language", "$top": max_results})

        with make_request(url) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if isinstance(body, dict) and "value" in body:
            items = body["value"]
            return json.dumps({
                "mode": "search",
                "search_query": description,
                "search_field": search_field,
                "language": language,
                "exact_match": exact_match,
                "found_products": len(items),
                "products": [
                    {
                        "Product": p.get("Product", ""),
                        "ProductDescription": p.get("ProductDescription", ""),
                        "Language": p.get("Language", ""),
                    } for p in items
                ],
            }, indent=2)
        return f"No products found matching: '{description}' (lang={language})"
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8") if e.fp else "No error details"
        return f"HTTP Error {e.code}: {e.reason}\nDetails: {details}"
    except Exception as e:
        return f"API call failed: {str(e)}"

@mcp.tool()
def generic_sap_search(
    service_path: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    data: Optional[str] = None,
) -> str:
    """Generic SAP OData call (V2/V4)."""
    try:
        base = get_sap_base_url(service_path)
        url = f"{base}&{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}" if params else base
        req = urllib.request.Request(url, data=(data.encode("utf-8") if data else None), method=method.upper())
        for k, v in {"Accept": "application/json", "Content-Type": "application/json", **(headers or {})}.items():
            req.add_header(k, v)
        _auth(req)
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8") if e.fp else "No error details"
        return f"Request failed with status {e.code}: {e.reason}\nDetails: {details}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"

@mcp.tool()
def post_to_sap(
    endpoint: str,
    payload: str,
    content_type: str = "application/json",
    additional_headers: Optional[Dict[str, str]] = None,
) -> str:
    """Dedicated POST to SAP (or any endpoint)."""
    try:
        url = endpoint if endpoint.startswith("http") else f"https://vhcals4hci.dummy.nodomain:44300/sap/opu/odata/sap/{endpoint.lstrip('/')}"
        req = urllib.request.Request(url, data=(payload.encode("utf-8") if payload else None), method="POST")
        req.add_header("Content-Type", content_type)
        req.add_header("Accept", "application/json")
        req.add_header("X-Requested-With", "XMLHttpRequest")
        _auth(req)
        if additional_headers:
            for k, v in additional_headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
            return json.dumps({
                "status_code": resp.getcode(),
                "status_message": "Success",
                "response_data": resp.read().decode("utf-8"),
                "url": url
            }, indent=2)
    except urllib.error.HTTPError as e:
        return json.dumps({
            "status_code": e.code,
            "status_message": f"HTTP Error: {e.reason}",
            "error_details": (e.read().decode("utf-8") if e.fp else "No error details"),
            "url": url
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "status_code": 500,
            "status_message": "Request Failed",
            "error_details": str(e),
            "url": url
        }, indent=2)

# ---------- Resources & Prompts ----------
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    return f"Hello, {name}!"

@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }
    return f"{styles.get(style, styles['friendly'])} for someone named {name}."

# ---------- ASGI entrypoint (Streamable HTTP on /mcp) ----------
# NOTE: Your FastMCP version exposes Streamable HTTP via streamable_http_app() (older versions).
app = mcp.streamable_http_app()   # mounted at /mcp by default

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Motiveminds MCP Server on http://0.0.0.0:8000/mcp ...")
    uvicorn.run(app, host="0.0.0.0", port=8000)

# # --- Entry point ---
# if __name__ == "__main__":
#     logger.info("Starting Motiveminds MCP Server (SSE) ...")
#     mcp.run("sse")   # <-- Correct way (no host/port here)
