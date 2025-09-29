import os
import logging
import urllib.request
import urllib.parse
import urllib.error
import base64
import ssl
import json
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastmcp import FastMCP

# ---------- Environment & Logging ----------
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MotivemindsMCP")

# Global token variables
_access_token = None
_token_expires_at = None

# ---------- Configuration Validation ----------
def validate_environment():
    """Validate required environment variables at startup"""
    required_vars = ["SAP_HOST", "AUTH_USERNAME", "AUTH_PASSWORD"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Validate SAP_HOST format
    sap_host = os.getenv("SAP_HOST")
    if not sap_host or not sap_host.startswith(("http://", "https://")):
        raise ValueError("SAP_HOST must include protocol (http:// or https://)")
    
    logger.info("Environment validation passed")

# Validate environment on startup
validate_environment()

# ---------- SSL Configuration ----------
# For production, use proper SSL context with certificate verification
# Only disable SSL verification for development/testing environments
if os.getenv("ENVIRONMENT", "production").lower() == "development":
    ssl_context = ssl._create_unverified_context()
    logger.warning("SSL verification disabled - DEVELOPMENT MODE ONLY")
else:
    ssl_context = ssl.create_default_context()
    logger.info("SSL verification enabled")

# ---------- MCP Server ----------
# Get port from environment (Render sets PORT automatically)
port = int(os.getenv("PORT", 8000))
host = os.getenv("HOST", "0.0.0.0")

# Create FastMCP server with stateless HTTP for deployment
mcp = FastMCP("MotivemindsMCPServer", stateless_http=True)

# Common configuration for SAP system
SAP_HOST      = os.getenv("SAP_HOST")
SAP_PORT      = os.getenv("SAP_PORT")
SAP_CLIENT    = os.getenv("SAP_CLIENT")
auth_username = os.getenv("AUTH_USERNAME")
auth_password = os.getenv("AUTH_PASSWORD")

SAP_SERVICES = {
    "business_partner": "sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Customer",
    "product_description": "/sap/opu/odata4/sap/api_product/srvd_a2x/sap/product/0001/ProductDescription",
    "sales_order": "sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder",
    "material_stock": "sap/opu/odata/sap/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod",  # Added
    "p2p": "/sap/opu/odata/sap/ZWORKFLOWSTS_SRV/WorkflowSet",  # Added
    "Budget": "/sap/opu/odata/sap/Z_WORKFLOW_SRV/RequestedOrder",
     # Add more here
}

############################################################
# Workflow 

def get_access_token() -> str:
    """Get or refresh OAuth2 access token from environment variables"""
    global _access_token, _token_expires_at
    
    if _access_token and _token_expires_at and datetime.now() < _token_expires_at:
        return _access_token
    
    token_url = os.getenv('SAP_BPA_TOKEN_URL')
    client_id = os.getenv('SAP_BPA_CLIENT_ID')
    client_secret = os.getenv('SAP_BPA_CLIENT_SECRET')
    
    if not all([token_url, client_id, client_secret]):
        raise Exception("Missing environment variables: SAP_BPA_TOKEN_URL, SAP_BPA_CLIENT_ID, SAP_BPA_CLIENT_SECRET")
    
    # Ensure token_url is a string before passing to Request
    if token_url is None:
        raise ValueError("token_url cannot be None at this point.")

    # Prepare auth data
    auth_data = f"grant_type=client_credentials&client_id={client_id}&client_secret={client_secret}"
    auth_data_bytes = auth_data.encode('utf-8')
    
    req = urllib.request.Request(token_url, data=auth_data_bytes, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_text = response.read().decode('utf-8')
            token_data = json.loads(response_text)
            
            _access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 3600)
            _token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)  # 60s buffer
            
            return _access_token
    except Exception as e:
        raise Exception(f"Failed to get access token: {str(e)}")

def make_bpa_request(endpoint: str, method: str = "GET", data: Optional[dict] = None):
    """Make authenticated request to SAP BPA API"""
    base_url = os.getenv('SAP_BPA_BASE_URL')
    if not base_url:
        raise Exception("Missing environment variable: SAP_BPA_BASE_URL")
    
    token = get_access_token()
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    
    req_data = None
    if data and method in ["POST", "PUT", "PATCH"]:
        req_data = json.dumps(data).encode('utf-8')
    
    req = urllib.request.Request(url, data=req_data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_text = response.read().decode('utf-8')
            return json.loads(response_text) if response_text else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else "No error details"
        raise Exception(f"HTTP Error {e.code}: {e.reason}\nURL: {url}\nDetails: {error_body}")

def extract_data_list(result):
    """Extract data from API response, handling both list and dict formats"""
    if isinstance(result, list):
        return result
    elif isinstance(result, dict) and 'value' in result:
        return result['value']
    elif isinstance(result, dict) and 'd' in result and 'results' in result['d']:
        return result['d']['results']  # OData v2 format
    elif isinstance(result, dict):
        return [result]  # Single object response
    else:
        return []
    
@mcp.tool()
def sap_bpa_get_user_task_instances(
    recipient_users: Optional[str] = None,
    limit: int = 5,
) -> str:
    """
    Get user open task instances from SAP Build Process Automation using the workflow/rest endpoint
    Returns latest 5 READY and RESERVED tasks ordered by lastChangedAt descending
    
    Args:
        recipient_users: Filter by recipient user email/ID (e.g., 'srinai01@GOODBABYINT.COM')
        limit: Maximum number of results to return (default: 5)
    """
    try:
        # Build query parameters as dictionary
        query_params = {
            "$filter": "status eq 'READY' or status eq 'RESERVED'",
            "$orderby": "lastChangedAt desc",
            "$top": limit
        }
        
        if recipient_users:
            query_params["recipientUsers"] = recipient_users
        
        # Convert to query string
        query_string = urllib.parse.urlencode(query_params)
        endpoint = f"/v1/task-instances?{query_string}"
        
        result = make_bpa_request(endpoint, "GET")
        data_list = extract_data_list(result)
        
        response = {
            "mode": "get_user_task_instances",
            "filters": {
                "recipient_users": recipient_users,
                "status": "READY or RESERVED", 
                "order_by": "lastChangedAt desc",
                "limit": limit
            },
            "total_count": len(data_list),
            "task_instances": data_list
        }
        
        return json.dumps(response, indent=2)
        
    except Exception as e:
        return f"Error getting user task instances: {str(e)}"
    
@mcp.tool()
def sap_bpa_get_task_instance_context(
    instance_id: str,
) -> str:
    """
    Get the context/variables of a task instance
    mcp tool user_task_instances has the Instance ID which is need to make this call

    Args:
        instance_id: Task instance ID
    """
    try:
        if not instance_id:
            return "Error: instance_id is required"
        
        endpoint = f"v1/task-instances/{instance_id}/context"
        result = make_bpa_request(endpoint, "GET")
        
        response = {
            "mode": "task_instance_context",
            "instance_id": instance_id,
            "context": result
        }
        
        return json.dumps(response, indent=2)
        
    except Exception as e:
        return f"Error getting process instance context: {str(e)}"

@mcp.tool()
def sap_bpa_debug_api_response(
    endpoint: str,
) -> str:
    """
    Debug tool to see raw API response format from SAP BPA
    
    Args:
        endpoint: API endpoint to test (e.g., 'v1/workflow-definitions')
    
    This tool helps troubleshoot API response formats by showing the raw JSON structure.
    """
    try:
        if not endpoint:
            return "Error: endpoint is required"
        
        result = make_bpa_request(endpoint, "GET")
        
        response = {
            "mode": "debug_api_response",
            "endpoint": endpoint,
            "response_type": type(result).__name__,
            "response_keys": list(result.keys()) if isinstance(result, dict) else "N/A (not a dict)",
            "raw_response": result
        }
        
        return json.dumps(response, indent=2)
        
    except Exception as e:
        return f"Error making API call: {str(e)}"

def get_sap_base_url(service_path: str) -> str:
    """
    Builds the full base SAP URL using the service path provided by the caller.
    Handles port configuration properly to avoid malformed URLs.
    """
    if not service_path:
        raise ValueError("Service path must be provided.")
    if not SAP_HOST:
        raise ValueError("SAP_HOST must be set (e.g. https://<host>).")
    if not SAP_CLIENT:
        raise ValueError("SAP_CLIENT must be set (e.g. 100).")
    
    # Parse the host to check if port is already included
    parsed_host = urlparse(SAP_HOST)
    
    # If port is already in the host, don't add it again
    if parsed_host.port:
        base_host = SAP_HOST
    else:
        # Only add port if it's not the default port for the scheme
        if (parsed_host.scheme == "https" and SAP_PORT != "443") or (parsed_host.scheme == "http" and SAP_PORT != "80"):
            base_host = f"{SAP_HOST}:{SAP_PORT}"
        else:
            base_host = SAP_HOST
    
    service_path = service_path.lstrip("/")
    return f"{base_host}/{service_path}?sap-client={SAP_CLIENT}"

def escape_odata_string(value: str) -> str:
    """Escape single quotes in OData string values to prevent injection"""
    return value.replace("'", "''")

def build_url_with_params(base_url: str, params: Dict[str, Any]) -> str:
    """Build URL with query parameters, handling existing parameters correctly"""
    if not params:
        return base_url
    
    # Check if base_url already has query parameters
    separator = "&" if "?" in base_url else "?"
    query_string = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"{base_url}{separator}{query_string}"

def make_sap_request(url: str, method: str = "GET", data: Optional[str] = None, 
                    headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> Dict[str, Any]:
    """Make a standardized SAP request with proper error handling"""
    try:
        req = urllib.request.Request(
            url, 
            data=(data.encode("utf-8") if data else None), 
            method=method.upper()
        )
        
        # Set default headers
        default_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Merge with additional headers
        if headers:
            default_headers.update(headers)
        
        for key, value in default_headers.items():
            req.add_header(key, value)
        
        # Add authentication
        if auth_username and auth_password:
            credentials = f"{auth_username}:{auth_password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode("utf-8")
            req.add_header("Authorization", f"Basic {encoded_credentials}")
        
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            response_data = resp.read().decode("utf-8")
            return {
                "success": True,
                "status_code": resp.getcode(),
                "data": json.loads(response_data) if response_data else None,
                "url": url
            }
            
    except urllib.error.HTTPError as e:
        error_details = e.read().decode("utf-8") if e.fp else "No error details"
        return {
            "success": False,
            "status_code": e.code,
            "error": f"HTTP Error {e.code}: {e.reason}",
            "details": error_details,
            "url": url
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": 500,
            "error": f"Request failed: {str(e)}",
            "url": url
        }

# ---------- TOOLS ----------

@mcp.tool()
def search_CustomerBy_CustomerDescription(
    description: str,
    search_field: str = "CustomerName",
    exact_match: bool = False,
    max_results: int = 10,
    base_url: Optional[str] = None,
) -> str:
    """
    Search customer numbers by customer description using SAP Business Partner API.
    
    Args:
        description: Customer description to search for
        search_field: Field to search in (CustomerName, CustomerFullName, etc.)
        exact_match: If True, searches for exact match; if False, uses contains
        max_results: Maximum number of results to return
        base_url: The SAP Business Partner API endpoint
        
    Returns:
        JSON response with customer data or error message.
        Never returns credentials (userid/password) or sensitive information.
    """
    try:
        # Use default base URL if none is provided
        if not base_url:
            service_path = SAP_SERVICES["business_partner"]
            base_url = get_sap_base_url(service_path)

        # Escape the description to prevent OData injection
        escaped_description = escape_odata_string(description)
        
        # Build OData filter based on search type
        if exact_match:
            filter_query = f"{search_field} eq '{escaped_description}'"
        else:
            # Use substringof for partial matching (OData V2)
            filter_query = f"substringof('{escaped_description}', {search_field}) eq true"

        # Build query parameters
        query_params = {
            "$filter": filter_query,
            "$select": "Customer,CustomerName,CustomerFullName",
            "$top": max_results
        }
        
        url = build_url_with_params(base_url, query_params)
        result = make_sap_request(url)
        
        if not result["success"]:
            return json.dumps({
                "error": result["error"],
                "details": result.get("details", ""),
                "status_code": result["status_code"]
            }, indent=2)
        
        data = result["data"]
        if "d" in data and "results" in data["d"]:
            customers = data["d"]["results"]
            response = {
                "search_query": description,
                "search_field": search_field,
                "exact_match": exact_match,
                "found_customers": len(customers),
                "customers": [
                    {
                        "Customer": customer.get("Customer", ""),
                        "CustomerName": customer.get("CustomerName", ""),
                        "CustomerFullName": customer.get("CustomerFullName", "")
                    }
                    for customer in customers
                ]
            }
            return json.dumps(response, indent=2)
        else:
            return json.dumps({
                "message": f"No customers found matching: '{description}'",
                "search_query": description,
                "found_customers": 0
            }, indent=2)

    except Exception as e:
        logger.error(f"Error in search_CustomerBy_CustomerDescription: {str(e)}")
        return json.dumps({
            "error": f"Unexpected error: {str(e)}",
            "search_query": description
        }, indent=2)

@mcp.tool()
def search_ProductBy_Description(
    description: Optional[str] = None,
    search_field: str = "ProductDescription",
    language: str = "EN",
    exact_match: bool = False,
    max_results: int = 10,
    product: Optional[str] = None,
    key_mode: str = "auto",
    service_version: str = "0002",
    base_url: Optional[str] = None,
) -> str:
    """
    Search product numbers by product description (OData V4) and/or fetch a single
    ProductDescription by keys using key-as-segment or parentheses key syntax.

    Modes:
      1) Search mode (contains/eq): provide 'description' (product=None)
      2) Direct key mode: provide 'product' (description optional/ignored)
         - key_mode='segment'  -> .../ProductDescription/<Product>/<Language>
         - key_mode='paren'    -> .../ProductDescription(Product='<P>',Language='<L>')
         - key_mode='auto'     -> try segment, then paren
         
    Args:
        description: Product description to search for (for search mode)
        search_field: Field to search in
        language: Language code for product descriptions
        exact_match: Whether to perform exact match or contains search
        max_results: Maximum number of results to return
        product: Product ID for direct lookup (for key mode)
        key_mode: Key access mode ('segment', 'paren', 'auto')
        service_version: Service version to use
        base_url: Optional custom base URL
        
    Returns:
        JSON with normalized structure.
    """
    try:
        def get_service_base_path(version: str) -> str:
            return f"/sap/opu/odata4/sap/api_product/srvd_a2x/sap/product/{version}/ProductDescription"

        def build_base_url() -> str:
            sp = get_service_base_path(service_version)
            return base_url or get_sap_base_url(sp)

        base = build_base_url()

        # Direct key fetch mode
        if product:
            escaped_product = escape_odata_string(product)
            escaped_language = escape_odata_string(language)
            
            # Build candidates based on key_mode
            candidates = []
            if key_mode in ("segment", "auto"):
                seg = (
                    base.rstrip("/")
                    + "/"
                    + urllib.parse.quote(escaped_product, safe="")
                    + "/"
                    + urllib.parse.quote(escaped_language, safe="")
                )
                seg = build_url_with_params(seg, {"$select": "Product,ProductDescription,Language"})
                candidates.append(("segment", seg))

            if key_mode in ("paren", "auto"):
                paren_key = f"(Product='{escaped_product}',Language='{escaped_language}')"
                paren = base.rstrip("/") + paren_key
                paren = build_url_with_params(paren, {"$select": "Product,ProductDescription,Language"})
                candidates.append(("paren", paren))

            last_err = None
            for mode, url in candidates:
                result = make_sap_request(url)
                
                if result["success"]:
                    data = result["data"]
                    # Single-entity: often a plain object; some gateways still wrap in "value"
                    if isinstance(data, dict) and "Product" in data:
                        products = [data]
                    elif isinstance(data, dict) and "value" in data:
                        products = data["value"] if isinstance(data["value"], list) else [data["value"]]
                    else:
                        products = []

                    response = {
                        "mode": f"key_{mode}",
                        "product_key": product,
                        "language": language,
                        "found_products": len(products),
                        "products": [
                            {
                                "Product": p.get("Product", ""),
                                "ProductDescription": p.get("ProductDescription", ""),
                                "Language": p.get("Language", ""),
                            }
                            for p in products
                        ],
                    }
                    if response["found_products"] == 0:
                        response["message"] = f"No ProductDescription found for {product}/{language}"
                    return json.dumps(response, indent=2)
                else:
                    last_err = result["error"]
                    if key_mode != "auto" or result["status_code"] not in (400, 404):
                        return json.dumps({
                            "error": result["error"],
                            "details": result.get("details", ""),
                            "mode": f"key_{mode}",
                            "product_key": product,
                            "language": language
                        }, indent=2)
            
            return json.dumps({
                "error": last_err or f"ProductDescription not found for {product}/{language}",
                "product_key": product,
                "language": language
            }, indent=2)

        # Search mode
        if not description:
            return json.dumps({
                "error": "Please provide either a 'description' for search mode, or a 'product' for direct key mode."
            }, indent=2)

        escaped_description = escape_odata_string(description)
        escaped_language = escape_odata_string(language)
        
        # Build OData V4 filter
        if exact_match:
            filter_query = f"{search_field} eq '{escaped_description}' and Language eq '{escaped_language}'"
        else:
            filter_query = f"contains({search_field}, '{escaped_description}') and Language eq '{escaped_language}'"

        query_params = {
            "$filter": filter_query,
            "$select": "Product,ProductDescription,Language",
            "$top": max_results,
        }

        url = build_url_with_params(base, query_params)
        result = make_sap_request(url)
        
        if not result["success"]:
            return json.dumps({
                "error": result["error"],
                "details": result.get("details", ""),
                "mode": "search",
                "search_query": description
            }, indent=2)
        
        data = result["data"]
        if isinstance(data, dict) and "value" in data:
            products = data["value"]
            response = {
                "mode": "search",
                "search_query": description,
                "search_field": search_field,
                "language": language,
                "exact_match": exact_match,
                "found_products": len(products),
                "products": [
                    {
                        "Product": p.get("Product", ""),
                        "ProductDescription": p.get("ProductDescription", ""),
                        "Language": p.get("Language", ""),
                    }
                    for p in products
                ],
            }
            return json.dumps(response, indent=2)
        else:
            return json.dumps({
                "message": f"No products found matching: '{description}' (lang={language})",
                "mode": "search",
                "search_query": description,
                "found_products": 0
            }, indent=2)

    except Exception as e:
        logger.error(f"Error in search_ProductBy_Description: {str(e)}")
        return json.dumps({
            "error": f"Unexpected error: {str(e)}",
            "search_query": description or "",
            "product_key": product or ""
        }, indent=2)

@mcp.tool()
def get_Material_Stock(
    material: str,
    plant: Optional[str] = None,
    storage_location: Optional[str] = None,
    max_results: int = 10,
    base_url: Optional[str] = None,
) -> str:
    """
    Get stock details for a given material using SAP Material Stock API.

    Args:
        material: The material number to check stock for
        plant: Optional plant ID to filter
        storage_location: Optional storage location to filter
        max_results: Maximum number of results to return
        base_url: Override the default SAP OData base URL if needed

    Returns:
        JSON response with stock data or error message.
    """
    try:
        # Use default service if base_url not provided
        if not base_url:
            service_path = SAP_SERVICES["material_stock"]
            base_url = get_sap_base_url(service_path)

        # Build OData filter with proper escaping
        escaped_material = escape_odata_string(material)
        filters = [f"Material eq '{escaped_material}'"]
        
        if plant:
            escaped_plant = escape_odata_string(plant)
            filters.append(f"Plant eq '{escaped_plant}'")
        if storage_location:
            escaped_location = escape_odata_string(storage_location)
            filters.append(f"StorageLocation eq '{escaped_location}'")

        filter_query = " and ".join(filters)

        query_params = {
            "$filter": filter_query,
            "$select": "Material,Plant,StorageLocation,MaterialBaseUnit,InventoryStockType,Batch,Supplier",
            "$top": max_results
        }

        url = build_url_with_params(base_url, query_params)
        result = make_sap_request(url)
        
        if not result["success"]:
            return json.dumps({
                "error": result["error"],
                "details": result.get("details", ""),
                "status_code": result["status_code"]
            }, indent=2)
        
        data = result["data"]
        if "d" in data and "results" in data["d"]:
            stocks = data["d"]["results"]
            response = {
                "material": material,
                "plant": plant,
                "storage_location": storage_location,
                "found_records": len(stocks),
                "stocks": stocks
            }
            return json.dumps(response, indent=2)
        else:
            return json.dumps({
                "message": f"No stock found for Material '{material}'",
                "material": material,
                "found_records": 0
            }, indent=2)

    except Exception as e:
        logger.error(f"Error in get_Material_Stock: {str(e)}")
        return json.dumps({
            "error": f"Unexpected error: {str(e)}",
            "material": material
        }, indent=2)

@mcp.tool()
def Looking_into_SAP(
    service_path: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    data: Optional[str] = None,
) -> str:
    """
    Generic SAP OData search/call tool (V2 or V4).

    Use this as a fallback when specific helper tools do not work, or when you need to query any
    SAP OData service directly. Host will give the Service path and Entity which we need to query 
    and based on the Query path we need to make API call.

    Args:
        service_path: Full OData service path (including version if applicable)
        method: HTTP method (GET, POST, etc.)
        headers: Optional dictionary of custom headers
        params: Optional dictionary of query parameters (e.g. {"$top": 10})
        data: Optional request body for POST/PUT in JSON string format

    Returns:
        JSON response with API data or sanitized error message.
    """
    try:
        # Build the base URL (host:port/service_path?sap-client=XXX)
        base_url = get_sap_base_url(service_path)
        url = build_url_with_params(base_url, params or {})
        
        result = make_sap_request(url, method, data, headers, timeout=30)
        
        if result["success"]:
            return json.dumps({
                "status_code": result["status_code"],
                "data": result["data"],
                "url": result["url"]
            }, indent=2)
        else:
            return json.dumps({
                "error": result["error"],
                "details": result.get("details", ""),
                "status_code": result["status_code"],
                "url": result["url"]
            }, indent=2)

    except Exception as e:
        logger.error(f"Error in Looking_into_SAP: {str(e)}")
        return json.dumps({
            "error": f"Unexpected error: {str(e)}",
            "service_path": service_path
        }, indent=2)

@mcp.tool()
def post_to_sap(
    service_path: str,
    payload: str,
    content_type: str = "application/json",
    additional_headers: Optional[Dict[str, str]] = None,
) -> str:
    """
    Dedicated tool for making POST calls to SAP systems.
    
    Args:
        service_path: SAP service path (will be constructed with SAP base URL)
        payload: JSON string or data to send in the POST body
        content_type: Content type for the request (default: application/json)
        additional_headers: Additional headers as a dictionary
        
    Returns:
        Response text or error message in JSON format.
    """
    try:
        # Use the configured SAP host instead of hardcoded URL
        base_url = get_sap_base_url(service_path)
        
        headers = {
            "Content-Type": content_type,
            "X-Requested-With": "XMLHttpRequest"
        }
        if additional_headers:
            headers.update(additional_headers)
        
        result = make_sap_request(base_url, "POST", payload, headers, timeout=30)
        
        return json.dumps({
            "status_code": result["status_code"],
            "success": result["success"],
            "data": result.get("data"),
            "error": result.get("error"),
            "details": result.get("details"),
            "url": result["url"]
        }, indent=2)

    except Exception as e:
        logger.error(f"Error in post_to_sap: {str(e)}")
        return json.dumps({
            "status_code": 500,
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "service_path": service_path
        }, indent=2)

# ---------- RESOURCES ----------

@mcp.resource("sap://config")
def get_sap_config() -> str:
    """Get current SAP configuration (without sensitive data)"""
    return json.dumps({
        "sap_host": SAP_HOST,
        "sap_port": SAP_PORT,
        "sap_client": SAP_CLIENT,
        "available_services": list(SAP_SERVICES.keys()),
        "ssl_verification": "enabled" if os.getenv("ENVIRONMENT", "production").lower() != "development" else "disabled"
    }, indent=2)

@mcp.resource("sap://services")
def get_sap_services() -> str:
    """Get available SAP services and their paths"""
    return json.dumps({
        "services": {
            name: {
                "path": path,
                "full_url": get_sap_base_url(path),
                "description": f"SAP {name.replace('_', ' ').title()} Service"
            }
            for name, path in SAP_SERVICES.items()
        }
    }, indent=2)

@mcp.resource("sap://service/{service_name}/metadata")
def get_service_metadata(service_name: str) -> str:
    """Get metadata for a specific SAP service"""
    if service_name not in SAP_SERVICES:
        return json.dumps({
            "error": f"Service '{service_name}' not found",
            "available_services": list(SAP_SERVICES.keys())
        }, indent=2)
    
    service_path = SAP_SERVICES[service_name]
    metadata_url = get_sap_base_url(service_path) + "/$metadata"
    
    return json.dumps({
        "service_name": service_name,
        "service_path": service_path,
        "metadata_url": metadata_url,
        "description": f"Metadata for SAP {service_name.replace('_', ' ').title()} Service"
    }, indent=2)

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}! Welcome to the MotiveMinds SAP MCP Server."

# ---------- PROMPTS ----------

@mcp.prompt()
def search_customer_prompt(customer_name: str, exact_match: bool = False) -> str:
    """
    Generate a prompt for searching customers in SAP.
    
    Args:
        customer_name: Name of the customer to search for
        exact_match: Whether to perform exact match search
    """
    return f"""You are helping to search for customers in the SAP system. 

Use the search_CustomerBy_CustomerDescription tool with these parameters:
- description: "{customer_name}"
- exact_match: {exact_match}
- search_field: "CustomerName"

This will search the SAP Business Partner API for customers matching the given name. 
The tool will return customer details including Customer ID, Customer Name, and Full Name.

If no results are found, try:
1. Using exact_match: false for broader search
2. Searching in different fields like "CustomerFullName"
3. Using partial names or different spelling variations
"""

@mcp.prompt()
def search_product_prompt(product_description: str, language: str = "EN") -> str:
    """
    Generate a prompt for searching products in SAP.
    
    Args:
        product_description: Description of the product to search for
        language: Language code for product descriptions
    """
    return f"""You are helping to search for products in the SAP system.

Use the search_ProductBy_Description tool with these parameters:
- description: "{product_description}"
- language: "{language}"
- exact_match: false (for broader search)

This will search the SAP Product API for products matching the given description.
The tool will return product details including Product ID, Product Description, and Language.

If you need to look up a specific product by its ID, use:
- product: "PRODUCT_ID" (instead of description)
- language: "{language}"

For better results, try:
1. Using key terms from the product description
2. Different language codes if available
3. Exact match for precise searches
"""

@mcp.prompt()
def material_stock_prompt(material: str, plant: Optional[str] = None) -> str:
    """
    Generate a prompt for checking material stock in SAP.
    
    Args:
        material: Material number to check
        plant: Optional plant to filter by
    """
    return f"""You are helping to check material stock in the SAP system.

Use the get_Material_Stock tool with these parameters:
- material: "{material}"
{f'- plant: "{plant}"' if plant else ''}

This will query the SAP Material Stock API for inventory information.
The tool will return stock details including quantities, storage locations, and units.

For comprehensive stock analysis:
1. Check stock across all plants if no plant is specified
2. Review different storage locations within plants
3. Consider batch information and supplier details
4. Check material base units for proper quantity interpretation
"""

@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt"""
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }
    return f"{styles.get(style, styles['friendly'])} for someone named {name} who is using the MotiveMinds SAP MCP Server."

@mcp.prompt()
def sap_integration_workflow(task_description: str) -> str:
    """
    Generate a comprehensive workflow prompt for SAP integration tasks.
    
    Args:
        task_description: Description of the SAP integration task
    """
    return f"""You are an SAP integration specialist helping with: {task_description}

Available SAP Tools:
1. search_CustomerBy_CustomerDescription - Find customers by name/description
2. search_ProductBy_Description - Find products by description or lookup by ID
3. get_Material_Stock - Check material inventory and stock levels
4. Looking_into_SAP - Make custom OData queries to any SAP service
5. post_to_sap - Send data to SAP services

Available Resources:
1. sap://config - Current SAP system configuration
2. sap://services - Available SAP services and endpoints
3. sap://service/{{service_name}}/metadata - Service-specific metadata

Workflow Steps:
1. First, check the SAP configuration using the sap://config resource
2. Review available services using the sap://services resource
3. Use appropriate search tools to find relevant data
4. If needed, use Looking_into_SAP for custom queries
5. Use post_to_sap for data updates or creation

Best Practices:
- Always validate data before posting to SAP
- Use exact_match: false for initial searches, then refine
- Check service metadata for available fields and operations
- Handle errors gracefully and provide meaningful feedback
- Consider plant and storage location filters for stock queries

Start by understanding the current SAP configuration and available services.
"""

# ---------- SERVER STARTUP ----------
if __name__ == "__main__":
    logger.info("Starting MotiveMinds MCP Server with Streamable HTTP...")
    logger.info("Server configured with FastMCP 2.0")
    logger.info("Server will be available at: http://localhost:8000/mcp/")
    mcp.run(transport="http", port=port)