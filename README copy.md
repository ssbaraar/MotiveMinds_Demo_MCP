# MotiveMinds MCP Server

A production-ready Model Context Protocol (MCP) server for SAP integration, built with FastMCP 2.0. Provides secure, optimized tools, resources, and prompts for interacting with SAP systems via OData APIs.

## 🚀 Features

### Enhanced Tools (5 Total)
- **search_CustomerBy_CustomerDescription**: Search customers in SAP Business Partner API with injection protection
- **search_ProductBy_Description**: Advanced product search with multiple key modes (segment/paren/auto)
- **get_Material_Stock**: Check material inventory across plants and storage locations
- **Looking_into_SAP**: Generic OData query tool for any SAP service
- **post_to_sap**: Secure POST operations to SAP services

### Smart Resources (4 Types)
- **sap://config**: Current SAP system configuration (sanitized)
- **sap://services**: Available SAP services with full URLs
- **sap://service/{service_name}/metadata**: Dynamic service metadata
- **greeting://{name}**: Personalized greeting resource

### Comprehensive Prompts (5 Templates)
- **search_customer_prompt**: Guided customer search workflow
- **search_product_prompt**: Product search with language support
- **material_stock_prompt**: Material inventory checking guidance
- **sap_integration_workflow**: Complete SAP integration workflow
- **greet_user**: Customizable greeting templates

## 🛡️ Security & Quality Improvements

### ✅ Security Enhancements
- **OData Injection Prevention**: All user inputs are properly escaped
- **SSL Verification**: Configurable SSL context (dev/prod modes)
- **Environment Validation**: Startup validation of required credentials
- **Sanitized Responses**: No sensitive data in error messages
- **Proper Authentication**: Secure credential handling

### ✅ Code Quality
- **Standardized Error Handling**: Consistent JSON error responses
- **Input Validation**: Comprehensive parameter validation
- **URL Construction**: Fixed port handling and malformed URL issues
- **Type Safety**: Full type hints and null checks
- **Logging**: Comprehensive logging with proper levels

### ✅ MCP Compliance
- **FastMCP 2.0**: Built with the latest FastMCP framework
- **Proper Resource Patterns**: URI-based resource identification
- **Structured Prompts**: Parameter schemas and usage guidance
- **Tool Schemas**: Comprehensive input/output documentation

## 🛠️ Installation

1. **Clone and setup**:
   ```bash
   git clone <repository-url>
   cd MotiveMinds_Demo_MCP
   uv venv
   ```

2. **Install dependencies**:
   ```bash
   uv pip install -r requirements.txt
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your SAP credentials
   ```

## ⚙️ Configuration

Your `.env` file should contain:

```env
# SAP Configuration
SAP_HOST=https://demo.motiveminds.com
SAP_PORT=44360
SAP_CLIENT=100

# Authentication
AUTH_USERNAME=CONVIA
AUTH_PASSWORD=Silver@123

# Environment (development/production)
ENVIRONMENT=development
```

## 🏃‍♂️ Running the Server

### Streamable HTTP Transport (Default)
The server is configured to run with Streamable HTTP transport for network accessibility:
```bash
uv run python main.py
```
**Server will be available at: `http://localhost:8000/mcp/`**

### STDIO Transport
For Claude Desktop and local development, modify the `mcp.run()` call in main.py:
```python
# Change from:
mcp.run(transport="http", host="0.0.0.0", port=8000)
# To:
mcp.run()  # Uses STDIO by default
```

### Using FastMCP CLI
```bash
# Install FastMCP CLI
uv pip install fastmcp

# Run with different options
fastmcp run main.py
fastmcp run main.py --transport http --port 8000
```

## 🧪 Testing

Run the comprehensive test suite:
```bash
uv run python test_server.py
```

**Test Coverage (10/10 tests):**
- ✅ Server imports and initialization
- ✅ Environment variable validation  
- ✅ URL construction with port handling
- ✅ OData string escaping (injection prevention)
- ✅ MCP server creation
- ✅ Tools registration framework
- ✅ Resources registration framework
- ✅ Prompts registration framework
- ✅ SAP request helper functionality
- ✅ SAP services configuration

## 📊 Available SAP Services

Pre-configured services with full security:

| Service | Description | API Version |
|---------|-------------|-------------|
| **business_partner** | Customer and vendor data | OData V2 |
| **product_description** | Product information | OData V4 |
| **sales_order** | Sales order management | OData V2 |
| **material_stock** | Inventory and stock levels | OData V2 |

## 🔧 Usage Examples

### Customer Search with Security
```python
{
  "description": "ACME Corp",
  "exact_match": false,
  "max_results": 10
}
# Automatically escapes special characters and prevents injection
```

### Advanced Product Lookup
```python
# Direct product lookup with multiple key modes
{
  "product": "PROD123",
  "language": "EN",
  "key_mode": "auto"  # Tries segment, then parentheses
}

# Fuzzy product search
{
  "description": "laptop computer",
  "language": "EN",
  "exact_match": false
}
```

### Material Stock Analysis
```python
{
  "material": "MAT001",
  "plant": "1000",
  "storage_location": "0001",
  "max_results": 20
}
```

### Generic SAP Queries
```python
{
  "service_path": "sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder",
  "params": {
    "$filter": "SalesOrganization eq '1000'",
    "$top": "5"
  }
}
```

## 🚨 Error Handling

All tools return standardized JSON responses:

```json
{
  "success": true/false,
  "status_code": 200,
  "data": {...},
  "error": "Error message if failed",
  "details": "Additional error context",
  "url": "Request URL for debugging"
}
```

## 🔒 Security Features

- **Environment-based SSL**: Production uses verified SSL, development allows unverified
- **Input Sanitization**: All OData queries are escaped to prevent injection
- **Credential Protection**: No sensitive data in logs or error responses
- **Startup Validation**: Required environment variables checked at boot
- **Proper Port Handling**: Prevents malformed URLs and connection issues

## 📖 MCP Integration

This server fully implements the Model Context Protocol:

- **Tools**: AI can invoke functions based on user context
- **Resources**: Applications can access structured data sources  
- **Prompts**: Users can invoke guided workflow templates

Compatible with:
- Claude Desktop
- Microsoft Copilot Studio
- Any MCP-compatible client

## 🎯 Production Ready

This server includes all production essentials:
- Comprehensive error handling
- Security best practices
- Performance optimizations
- Proper logging and monitoring
- Full test coverage
- Documentation and examples

## 📚 Documentation

- **MCP Protocol**: https://modelcontextprotocol.io/
- **FastMCP 2.0**: https://gofastmcp.com/
- **SAP OData**: SAP API Business Hub

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with proper security considerations
4. Run the test suite: `uv run python test_server.py`
5. Ensure all 10/10 tests pass
6. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

**Built with FastMCP 2.0 • Production-Ready • Security-First • Fully Tested**