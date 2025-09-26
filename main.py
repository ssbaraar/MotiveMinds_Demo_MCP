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

from dotenv import load_dotenv
from fastmcp import FastMCP

# ---------- Environment & Logging ----------
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MotivemindsMCP")

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
mcp = FastMCP("MotivemindsMCPServer")

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

@mcp.tool()
def search_p2p_request(
    description: str,
    search_field: str = "ReqId",  # Can be ReqId only
    exact_match: bool = False,
    max_results: int = 10,
    base_url: Optional[str] = None,
) -> str:
    """
    Search request by ReqId using SAP Z_WORKFLOW_SRV API
    Args:
        description: Request ID
        search_field: Field to search in (ReqId)
        exact_match: If True, searches for exact match; if False, uses contains
        max_results: Maximum number of results to return
        base_url: The SAP Z_WORKFLOW_SRV API endpoint
    Returns:
        JSON response with customer data or error message
        Never return credentials(userid/password) or sensitive information
    """
    try:
        
        # Use default base URL if none is provided
        if not base_url:
            service_path = SAP_SERVICES["p2p"]
            base_url = get_sap_base_url(service_path)

        # URL encode the description to handle spaces and special characters
        encoded_description = urllib.parse.quote(description)
  
        # Build OData filter based on search type
        if exact_match:
            filter_query = f"{search_field} eq '{description}'"
        else:
            # Use substringof for partial matching (OData V2)
            filter_query = f"substringof('{description}', {search_field}) eq true"

        # Select relevant fields
        select_query = "$select=InvText,ReqId,CompCd,Zstatus1,Zstatus2,ReqEmail"
        
        # Add top parameter to limit results
        top_query = f"$top={max_results}"
        
        # Build query dict instead of raw strings
        query_params = {
            "$filter": filter_query,
            "$select": "InvText,ReqId,Short_Text,ZpoNum,WFInstance,Zsupnam,WfType,CompCd,CompTxt,CostCt,ReqTyp,IntOrd,ReqBy,ReqEmail,ReqDt,Zstatus1,Zstatus2,ReqBudYr1,ReqBudYr2,ReqBudTot,BudDoc,Zbudcomments,PurTyp,PurOrg,PurOrgDEsc,Zplant,PurOrd,Zsup,Zcurr,Zprcomments,ZCurrent_appr,Zappr_email",
            "$top": max_results
                    }
        
        # Encode params
        encoded_query = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
 
        # Combine with base_url
        url = f"{base_url}&{encoded_query}"
                
        # Prepare request
        req = urllib.request.Request(url, method="GET")
        
        # Headers for SAP OData service
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "userid":"srinai01@GOODBABYINT.COM"
        }
        
        for key, value in headers.items():
            req.add_header(key, value)

        # Basic Auth
        if auth_username and auth_password:
            credentials = f"{auth_username}:{auth_password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode("utf-8")
            req.add_header("Authorization", f"Basic {encoded_credentials}")
        
        
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            response_text = response.read().decode("utf-8")
            
            import json
            data = json.loads(response_text)
            
            # Process response
            if 'd' in data and 'results' in data['d']:
                requests = data['d']['results']
                result = {
                    "search_query": description,
                    "search_field": search_field,
                    "exact_match": exact_match,
                    "found_requests": len(requests),
                    "requests": []
                }
             
                for request in requests:
                    request_info = {
                        "Invoice Text": request.get("InvText", ""),
                        "Request ID": request.get("ReqId", ""),
                        "Request Type": request.get("ReqTyp", ""),
                        "Short Text": request.get("Short_Text", ""),
                        "PO Number": request.get("ZpoNum", ""),
                        "WF Instance": request.get("WFInstance", ""),                        
                        "CompanyC ode": request.get("CompCd", ""),
                        "Company Code Descruption": request.get("ComCompTxtpCd", ""),
                        "Cost Center": request.get("CostCt", ""),
                        "Internal Order": request.get("IntOrd", ""),
                        "Requested By": request.get("ReqBy", ""),
                        "Request Email": request.get("ReqEmail", ""),
                        "Requested On": request.get("ReqDt", ""),
                        "Current Year Budget": request.get("ReqBudYr1", ""),
                        "Next Year Budget": request.get("ReqBudYr2", ""),
                        "Total Budget": request.get("ReqBudTot", ""),
                        "Budget Document": request.get("BudDoc", ""),
                        "Comments During Approval": request.get("Zbudcomments", ""),
                        "Purchase Type": request.get("PurTyp", ""),
                        "Purchase Org": request.get("PurOrg", ""),
                        "Purchase Org Description": request.get("PurOrgDEsc", ""),
                        "Plant": request.get("Zplant", ""),
                        "Purchase Order": request.get("PurOrd", ""),
                        "Supplier": request.get("Zsup", ""),
                        "Supplier Name": request.get("Zsupnam", ""),
                        "Currency": request.get("Zcurr", ""),
                        "Latest Comment": request.get("Zprcomments", ""),
                        "Current Approver": request.get("ZCurrent_appr", ""),
                        "Current Approver Email": request.get("Zappr_email", ""),
                        "Workflow Status": request.get("Zstatus1", ""),
                        "Request Status": request.get("Zstatus2", "")                   }
                    result["requests"].append(request_info)
                
                return json.dumps(result, indent=2)
            else:
                return f"No request found matching: '{description}'"

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else "No error details"
        return f"HTTP Error {e.code}: {e.reason}\nURL: {url}\nDetails: {error_body}"
    except Exception as e:
        return f"API call failed: {str(e)}"

@mcp.tool()
def get_internal_order_budget(
    internal_order: str,
) -> str:
    """
    Get internal order budget information using SAP Z_WORKFLOW_SRV API
    
    Args:
        internal_order: Internal Order number (e.g., 'DE021503')
    Returns:
        JSON response with internal order budget data or error message
        Never return credentials(userid/password) or sensitive information
    """
    try:
        # Get service path and build base URL
        service_path = SAP_SERVICES["Budget"]
        base_url = get_sap_base_url(service_path)

        # Build OData filter for exact match on InternalOrder
        filter_query = f"InternalOrder eq '{internal_order}'"
        
        # Build query dict
        query_params = {
            "$filter": filter_query,
            "$select": "Currency,FiscalYear,InternalOrder,PlanVersion0,PlanVersion1,Budget,Actual,Commitment,Allotted,Available"
        }
        
        # Encode params
        encoded_query = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
        
        # Combine with base_url
        url = f"{base_url}&{encoded_query}"
        
        # Prepare request
        req = urllib.request.Request(url, method="GET")
        
        # Headers for SAP OData service
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        for key, value in headers.items():
            req.add_header(key, value)

        # Basic Auth
        if auth_username and auth_password:
            credentials = f"{auth_username}:{auth_password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode("utf-8")
            req.add_header("Authorization", f"Basic {encoded_credentials}")
        
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            response_text = response.read().decode("utf-8")
            
            import json
            data = json.loads(response_text)
            
            # Process response
            if 'd' in data and 'results' in data['d']:
                orders = data['d']['results']
                result = {
                    "internal_order": internal_order,
                    "found_orders": len(orders),
                    "orders": []
                }
                
                for order in orders:
                    order_info = {
                        "Internal Order": order.get("InternalOrder", ""),
                        "Currency": order.get("Currency", ""),
                        "Fiscal Year": order.get("FiscalYear", ""),
                        "Plan Version 0": order.get("PlanVersion0", ""),
                        "Plan Version 1": order.get("PlanVersion1", ""),
                        "Budget": order.get("Budget", ""),
                        "Actual": order.get("Actual", ""),
                        "Commitment": order.get("Commitment", ""),
                        "Allotted": order.get("Allotted", ""),
                        "Available": order.get("Available", "")
                    }
                    result["orders"].append(order_info)
                
                return json.dumps(result, indent=2)
            else:
                return f"No internal order found matching: '{internal_order}'"

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else "No error details"
        return f"HTTP Error {e.code}: {e.reason}\nURL: {url}\nDetails: {error_body}"
    except Exception as e:
        return f"API call failed: {str(e)}"

@mcp.tool()
def search_CustomerBy_CustomerDescription(
    description: str,
    search_field: str = "CustomerName",  # Can be CustomerName, CustomerFullName, etc.
    exact_match: bool = False,
    max_results: int = 10,
    base_url: Optional[str] = None,
) -> str:
    """
    Search customer numbers by customer description using SAP Business Partner API
    Args:
        description: Customer description to search for
        search_field: Field to search in (CustomerName, CustomerFullName, etc.)
        exact_match: If True, searches for exact match; if False, uses contains
        max_results: Maximum number of results to return
        base_url: The SAP Business Partner API endpoint
    Returns:
        JSON response with customer data or error message
        Never return credentials(userid/password) or sensitive information
    """
    try:
        
        # Use default base URL if none is provided
        if not base_url:
            service_path = SAP_SERVICES["business_partner"]
            base_url = get_sap_base_url(service_path)

        # URL encode the description to handle spaces and special characters
        encoded_description = urllib.parse.quote(description)
  
        # Build OData filter based on search type
        if exact_match:
            filter_query = f"{search_field} eq '{description}'"
        else:
            # Use substringof for partial matching (OData V2)
            filter_query = f"substringof('{description}', {search_field}) eq true"

        # Select relevant fields
        select_query = "$select=Customer,CustomerName,CustomerFullName"
        
        # Add top parameter to limit results
        top_query = f"$top={max_results}"
        
        # Build query dict instead of raw strings
        query_params = {
            "$filter": filter_query,
            "$select": "Customer,CustomerName,CustomerFullName",
            "$top": max_results
                    }
        
        # Encode params
        encoded_query = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
 
        # Combine with base_url
        url = f"{base_url}&{encoded_query}"
                
        # Prepare request
        req = urllib.request.Request(url, method="GET")
        
        # Headers for SAP OData service
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        for key, value in headers.items():
            req.add_header(key, value)

        # Basic Auth
        if auth_username and auth_password:
            credentials = f"{auth_username}:{auth_password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode("utf-8")
            req.add_header("Authorization", f"Basic {encoded_credentials}")
        
        
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            response_text = response.read().decode("utf-8")
            
            import json
            data = json.loads(response_text)
            
            # Process response
            if 'd' in data and 'results' in data['d']:
                customers = data['d']['results']
                result = {
                    "search_query": description,
                    "search_field": search_field,
                    "exact_match": exact_match,
                    "found_customers": len(customers),
                    "customers": []
                }
                
                for customer in customers:
                    customer_info = {
                        "Customer": customer.get("Customer", ""),
                        "CustomerName": customer.get("CustomerName", ""),
                        "CustomerFullName": customer.get("CustomerFullName", "")                    }
                    result["customers"].append(customer_info)
                
                return json.dumps(result, indent=2)
            else:
                return f"No customers found matching: '{description}'"

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else "No error details"
        return f"HTTP Error {e.code}: {e.reason}\nURL: {url}\nDetails: {error_body}"
    except Exception as e:
        return f"API call failed: {str(e)}"

@mcp.tool()
def search_ProductBy_Description(
    description: Optional[str] = None,          # when None and product set => direct key fetch path
    search_field: str = "ProductDescription",          # for search mode
    language: str = "EN",                       # default language
    exact_match: bool = False,
    max_results: int = 10,
    product: Optional[str] = None,              # when set => direct key fetch
    key_mode: str = "auto",                     # 'segment' | 'paren' | 'auto'
    service_version: str = "0002",              # supports 0001 / 0002 etc.
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
    Returns JSON with normalized structure.
    """
    try:
        import urllib.parse, urllib.request, json, base64, ssl

        def get_service_base_path(version: str) -> str:
            return f"/sap/opu/odata4/sap/api_product/srvd_a2x/sap/product/{version}/ProductDescription"

        def append_query(u: str, params: dict) -> str:
            qp = {k: v for k, v in params.items() if v is not None}
            if not qp:
                return u
            qs = urllib.parse.urlencode(qp, quote_via=urllib.parse.quote)
            sep = "&" if "?" in u else "?"
            return f"{u}{sep}{qs}"

        def build_base_url() -> str:
            sp = get_service_base_path(service_version)
            return base_url or get_sap_base_url(sp)

        def make_request(url: str):
            req = urllib.request.Request(url, method="GET")
            # V4-friendly headers
            req.add_header("Accept", "application/json")
            req.add_header("Content-Type", "application/json")
            # Basic auth if available
            if auth_username and auth_password:
                credentials = f"{auth_username}:{auth_password}"
                encoded_credentials = base64.b64encode(credentials.encode()).decode("utf-8")
                req.add_header("Authorization", f"Basic {encoded_credentials}")
            return urllib.request.urlopen(req, timeout=30, context=ssl_context)

        base = build_base_url()

        # --------------------------
        # Mode 2: Direct key fetch
        # --------------------------
        if product:
            # Build candidates based on key_mode
            candidates = []
            if key_mode in ("segment", "auto"):
                seg = (
                    base.rstrip("/")
                    + "/"
                    + urllib.parse.quote(product, safe="")
                    + "/"
                    + urllib.parse.quote(language, safe="")
                )
                # You may still $select on a single-entity request
                seg = append_query(seg, {"$select": "Product,ProductDescription,Language"})
                candidates.append(("segment", seg))

            if key_mode in ("paren", "auto"):
                # In V4, string keys must be quoted
                paren_key = f"(Product='{product}',Language='{language}')"
                paren = base.rstrip("/") + paren_key
                paren = append_query(paren, {"$select": "Product,ProductDescription,Language"})
                candidates.append(("paren", paren))

            last_err = None
            for mode, url in candidates:
                try:
                    with make_request(url) as resp:
                        body = resp.read().decode("utf-8")
                        data = json.loads(body)

                        # Single-entity: often a plain object; some gateways still wrap in "value"
                        if isinstance(data, dict) and "Product" in data:
                            products = [data]
                        elif isinstance(data, dict) and "value" in data:
                            products = data["value"] if isinstance(data["value"], list) else [data["value"]]
                        else:
                            products = []

                        result = {
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
                        if result["found_products"] == 0:
                            return json.dumps(
                                {"message": f"No ProductDescription found for {product}/{language}", **result},
                                indent=2,
                            )
                        return json.dumps(result, indent=2)
                except urllib.error.HTTPError as e:
                    # If auto, try the other style on 400/404; otherwise propagate
                    last_err = f"HTTP Error {e.code}: {e.reason}\nURL: {url}\nDetails: {(e.read().decode('utf-8') if e.fp else 'No details')}"
                    if key_mode != "auto" or e.code not in (400, 404):
                        return last_err
                except Exception as e:
                    last_err = f"API call failed: {str(e)}"
                    if key_mode != "auto":
                        return last_err
            return last_err or f"ProductDescription not found for {product}/{language}"

        # --------------------------
        # Mode 1: Search by description
        # --------------------------
        if not description:
            return "Please provide either a 'description' for search mode, or a 'product' for direct key mode."

        # Build OData V4 filter
        if exact_match:
            filter_query = f"{search_field} eq '{description}' and Language eq '{language}'"
        else:
            filter_query = f"contains({search_field}, '{description}') and Language eq '{language}'"

        query_params = {
            "$filter": filter_query,
            "$select": "Product,ProductDescription,Language",
            "$top": max_results,
        }

        url = append_query(base, query_params)

        with make_request(url) as response:
            response_text = response.read().decode("utf-8")
            data = json.loads(response_text)

            # V4 list payload
            if isinstance(data, dict) and "value" in data:
                products = data["value"]
                result = {
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
                return json.dumps(result, indent=2)
            else:
                return f"No products found matching: '{description}' (lang={language})"

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else "No error details"
        return f"HTTP Error {e.code}: {e.reason}\nURL: {url}\nDetails: {error_body}"
    except Exception as e:
        return f"API call failed: {str(e)}"


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
        material: The material number to check stock for.
        plant: Optional plant ID to filter.
        storage_location: Optional storage location to filter.
        max_results: Maximum number of results to return.
        base_url: Override the default SAP OData base URL if needed.

    Returns:
        JSON response with stock data or error message.
    """
    try:
        # Use default service if base_url not provided
        if not base_url:
            service_path = SAP_SERVICES["material_stock"]
            base_url = get_sap_base_url(service_path)

        # Build OData filter
        filters = [f"Material eq '{material}'"]
        if plant:
            filters.append(f"Plant eq '{plant}'")
        if storage_location:
            filters.append(f"StorageLocation eq '{storage_location}'")

        filter_query = " and ".join(filters)

        query_params = {
            "$filter": filter_query,
            "$select": "Material,Plant,StorageLocation,MaterialBaseUnit,InventoryStockType,Batch,Supplier",
            "$top": max_results
        }

        encoded_query = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
        url = f"{base_url}&{encoded_query}"

        # Request
        req = urllib.request.Request(url, method="GET")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        for key, value in headers.items():
            req.add_header(key, value)

        # Auth
        if auth_username and auth_password:
            credentials = f"{auth_username}:{auth_password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode("utf-8")
            req.add_header("Authorization", f"Basic {encoded_credentials}")

        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            response_text = response.read().decode("utf-8")
            import json
            data = json.loads(response_text)

            if "d" in data and "results" in data["d"]:
                stocks = data["d"]["results"]
                result = {
                    "material": material,
                    "plant": plant,
                    "storage_location": storage_location,
                    "found_records": len(stocks),
                    "stocks": stocks
                }
                return json.dumps(result, indent=2)
            else:
                return f"No stock found for Material '{material}'"

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else "No error details"
        return f"HTTP Error {e.code}: {e.reason}\nURL: {url}\nDetails: {error_body}"
    except Exception as e:
        return f"API call failed: {str(e)}"


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
    SAP OData service directly.
    Host will give the Serive path and Entity which we need to query and based on the Query path we need to make API call

    Args:
        service_path: Full OData service path (including version if applicable).
        method: HTTP method (GET).
        headers: Optional dictionary of custom headers.
        params: Optional dictionary of query parameters (e.g. {"$top": 10}).
        data: Optional request body for POST/PUT in JSON string format.

    Returns:
        API response as plain text (JSON/XML depending on service), or a sanitized error message.
    """
    try:
       # import urllib.parse, urllib.request, base64, logging

        # Build the base URL (host:port/service_path?sap-client=XXX)
        base_url = get_sap_base_url(service_path)

        # Append query parameters if provided
        if params:
            query_string = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            url = f"{base_url}&{query_string}"
        else:
            url = base_url

        # Encode request body if present
        encoded_data = data.encode("utf-8") if data else None

        # Prepare the request
        req = urllib.request.Request(url, data=encoded_data, method=method.upper())

        # Default headers
        default_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Merge user-provided headers (if any)
        if headers:
            default_headers.update(headers)

        for key, value in default_headers.items():
            req.add_header(key, value)

        # Add Basic Auth
        if auth_username and auth_password:
            credentials = f"{auth_username}:{auth_password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode("utf-8")
            req.add_header("Authorization", f"Basic {encoded_credentials}")

        # Make the request
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            return response.read().decode("utf-8")

    except urllib.error.HTTPError as e:
        logging.error(f"HTTP Error: {e.code}")
        error_details = e.read().decode("utf-8") if e.fp else "No error details"
        return f"Request failed with status {e.code}: {e.reason}\nDetails: {error_details}"

    except Exception as e:
        logging.exception("Unexpected error during API call")
        return f"Unexpected error: {str(e)}"

# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"

# Add a prompt
@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt"""
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }
    return f"{styles.get(style, styles['friendly'])} for someone named {name}."

if __name__ == "__main__":
    logger.info("Starting MotiveMinds MCP Server with Streamable HTTP...")
    logger.info("Server configured with FastMCP 2.0")
    logger.info("Server will be available at: http://localhost:8000/mcp/")
    mcp.run(transport="http", host="0.0.0.0", port=8000)
    