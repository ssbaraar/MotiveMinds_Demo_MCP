import os
import logging
import tempfile
import requests
import zipfile
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from pyngrok import ngrok, conf
import threading
import time
import platform
import asyncio
import json

# Import your existing MCP server
from main import mcp  # Replace 'your_mcp_file' with your actual filename

load_dotenv(dotenv_path='.env')

# Flask app setup
app = Flask(__name__)
app.config['DEBUG'] = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "SAP MCP Server"}), 200

def _run_coroutine_in_thread(coro):
    """Run a coroutine in a fresh event loop inside a thread and return its result."""
    result = {}
    def _runner():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result['value'] = loop.run_until_complete(coro)
        finally:
            loop.close()
    t = threading.Thread(target=_runner)
    t.start()
    t.join()
    return result.get('value')

def run_sync(coro_or_value):
    """If argument is a coroutine, run it and return result; otherwise return value."""
    if asyncio.iscoroutine(coro_or_value):
        try:
            # Preferred: use asyncio.run when no running loop
            return asyncio.run(coro_or_value)
        except RuntimeError:
            # Fallback: run in separate thread if an event loop is already running
            return _run_coroutine_in_thread(coro_or_value)
    return coro_or_value

@app.route('/api/sap/customer/search', methods=['POST'])
def search_customer():
    """API endpoint for customer search"""
    try:
        data = request.get_json()
        description = data.get('description', '')
        search_field = data.get('search_field', 'BusinessPartnerName') # Changed default
        exact_match = data.get('exact_match', False)
        max_results = data.get('max_results', 10)

        sap_host = os.getenv("SAP_HOST")
        sap_port = os.getenv("SAP_PORT")
        sap_client = os.getenv("SAP_CLIENT")

        if not all([sap_host, sap_port, sap_client]):
            return jsonify({"success": False, "error": "SAP connection details are not configured in .env file."}), 500

        base_url = f"{sap_host}:{sap_port}/sap/opu/odata/sap/API_BUSINESS_PARTNER"
        service_path = "/A_BusinessPartner"
        url = f"{base_url}{service_path}"

        if exact_match:
            filter_query = f"{search_field} eq '{description}'"
        else:
            filter_query = f"contains({search_field}, '{description}')"

        params = {
            "sap-client": sap_client,
            "$filter": filter_query,
            "$top": str(max_results),
            "$format": "json"
        }

        # Call your MCP tool
        result_obj = run_sync(mcp.call_tool('call_api', {
            'url': url,
            'method': 'GET',
            'params': params,
            'headers': {'Accept': 'application/json'}
        }))
        
        # Handle tuple or list response if necessary
        if isinstance(result_obj, (tuple, list)) and result_obj:
            result_str = result_obj[0]
        else:
            result_str = result_obj

        result = json.loads(result_str)
        return jsonify({"success": True, "data": result}), 200
    except Exception as e:
        logger.error(f"Customer search error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/sap/product/search', methods=['POST'])
def search_product():
    """API endpoint for product search"""
    try:
        data = request.get_json()
        description = data.get('description')
        search_field = data.get('search_field', 'ProductDescription')
        language = data.get('language', 'EN')
        exact_match = data.get('exact_match', False)
        max_results = data.get('max_results', 10)

        sap_host = os.getenv("SAP_HOST")
        sap_port = os.getenv("SAP_PORT")
        sap_client = os.getenv("SAP_CLIENT")

        if not all([sap_host, sap_port, sap_client]):
            return jsonify({"success": False, "error": "SAP connection details are not configured in .env file."}), 500

        # NOTE: You might need to adjust the service path for your specific SAP system
        base_url = f"{sap_host}:{sap_port}/sap/opu/odata/sap/API_PRODUCT_SRV"
        service_path = "/A_Product"
        url = f"{base_url}{service_path}"

        if exact_match:
            filter_query = f"{search_field} eq '{description}'"
        else:
            filter_query = f"contains({search_field}, '{description}')"

        params = {
            "sap-client": sap_client,
            "$filter": filter_query,
            "$top": str(max_results),
            "sap-language": language,
            "$format": "json"
        }

        # Call your MCP tool
        result_obj = run_sync(mcp.call_tool('call_api', {
            'url': url,
            'method': 'GET',
            'params': params,
            'headers': {'Accept': 'application/json'}
        }))

        # Handle tuple or list response if necessary
        if isinstance(result_obj, (tuple, list)) and result_obj:
            result_str = result_obj[0]
        else:
            result_str = result_obj

        result = json.loads(result_str)
        return jsonify({"success": True, "data": result}), 200
    except Exception as e:
        logger.error(f"Product search error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/sap/generic', methods=['POST'])
def generic_sap_call():
    """Generic SAP API call endpoint"""
    try:
        data = request.get_json()
        service_path = data.get('service_path', '')
        method = data.get('method', 'GET')
        headers = data.get('headers', {})
        params = data.get('params', {})
        request_data = data.get('data')

        sap_host = os.getenv("SAP_HOST")
        sap_port = os.getenv("SAP_PORT")
        sap_client = os.getenv("SAP_CLIENT")

        if not all([sap_host, sap_port, sap_client]):
            return jsonify({"success": False, "error": "SAP connection details are not configured in .env file."}), 500

        url = f"{sap_host}:{sap_port}{service_path}"

        # Add sap-client to params if not already there
        if 'sap-client' not in params:
            params['sap-client'] = sap_client

        # Call your MCP tool
        result_obj = run_sync(mcp.call_tool('call_api', {
            'url': url,
            'method': method,
            'headers': headers,
            'params': params,
            'data': request_data
        }))

        # Handle tuple or list response if necessary
        if isinstance(result_obj, (tuple, list)) and result_obj:
            result_str = result_obj[0]
        else:
            result_str = result_obj
            
        result = json.loads(result_str)
        return jsonify({"success": True, "data": result}), 200
    except Exception as e:
        logger.error(f"Generic SAP call error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

def download_ngrok():
    """Manually download ngrok to avoid Windows path issues"""
    ngrok_dir = os.path.join(os.getcwd(), 'ngrok_bin')
    ngrok_exe = os.path.join(ngrok_dir, 'ngrok')
    
    # Check if ngrok already exists
    if os.path.exists(ngrok_exe):
        return ngrok_exe
    
    try:
        os.makedirs(ngrok_dir, exist_ok=True)
        
        # Download ngrok manually
        print("📥 Downloading ngrok...")
        
        system = platform.system()
        if system == "Darwin":
            url = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-darwin-amd64.zip"
        elif system == "Windows":
            url = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
            ngrok_exe = os.path.join(ngrok_dir, 'ngrok.exe')
        else:
            url = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.zip"

        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        zip_path = os.path.join(ngrok_dir, 'ngrok.zip')
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Extract ngrok
        print("📦 Extracting ngrok...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(ngrok_dir)
        
        # Clean up zip file
        os.remove(zip_path)
        
        if os.path.exists(ngrok_exe):
            print("✅ ngrok downloaded successfully")
            return ngrok_exe
        else:
            print("❌ ngrok executable not found after extraction")
            return None
            
    except Exception as e:
        print(f"❌ Failed to download ngrok: {str(e)}")
        return None

def start_ngrok():
    """Start ngrok tunnel"""
    try:
        # Download ngrok manually to avoid path issues
        ngrok_exe = download_ngrok()
        if not ngrok_exe:
            return None
        
        # Set a custom ngrok path to avoid Windows path issues
        ngrok_dir = os.path.join(os.getcwd(), 'ngrok_bin')
        
        # Configure pyngrok to use our custom directory
        conf.get_default().ngrok_path = ngrok_exe
        conf.get_default().config_path = os.path.join(ngrok_dir, 'ngrok.yml')
        
        # Kill any existing ngrok processes
        ngrok.kill()
        
        # Set ngrok auth token
        ngrok_auth_token = os.getenv("NGROK_AUTH_TOKEN")
        if ngrok_auth_token:
            ngrok.set_auth_token(ngrok_auth_token)

        # Start ngrok tunnel
        print("🚀 Starting ngrok tunnel...")
        public_url = ngrok.connect("5002", "http")
        logger.info(f"ngrok tunnel started: {public_url}")
        
        # Save the URL to a file for reference
        with open('ngrok_url.txt', 'w') as f:
            f.write(str(public_url))
            
        return str(public_url)
    except Exception as e:
        logger.error(f"Failed to start ngrok: {str(e)}")
        print(f"❌ ngrok error details: {str(e)}")
        print("💡 Trying to run without ngrok tunnel...")
        return None

if __name__ == '__main__':
    # Start ngrok in a separate thread
    # ngrok_url = start_ngrok()
    ngrok_url = None # Force running locally for testing
    
    if ngrok_url:
        print(f"🚀 Server will be accessible at: {ngrok_url}")
        print(f"📋 API Endpoints available:")
        print(f"   - Health: {ngrok_url}/health")
        print(f"   - Customer Search: {ngrok_url}/api/sap/customer/search")
        print(f"   - Product Search: {ngrok_url}/api/sap/product/search")
        print(f"   - Generic SAP: {ngrok_url}/api/sap/generic")
    else:
        print("🚀 Server running locally at: http://localhost:5002")
        print(f"📋 API Endpoints available:")
        print(f"   - Health: http://localhost:5002/health")
        print(f"   - Customer Search: http://localhost:5002/api/sap/customer/search")
        print(f"   - Product Search: http://localhost:5002/api/sap/product/search")
        print(f"   - Generic SAP: http://localhost:5002/api/sap/generic")
    
    # Start Flask app regardless of ngrok status
    print("🔄 Starting Flask server...")
    app.run(host='0.0.0.0', port=5002, debug=False)
