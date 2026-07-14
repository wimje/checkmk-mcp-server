# Getting Started with Checkmk MCP Server

This guide walks you through setting up the Checkmk MCP Server from installation to your first natural language monitoring query.

## Overview

The Checkmk MCP Server acts as a bridge between AI assistants and your Checkmk monitoring infrastructure. Once set up, you can use natural language to monitor, manage, and analyze your infrastructure through any MCP-compatible AI client.

## Prerequisites

### System Requirements
- **Python**: 3.8 or higher
- **Operating System**: Windows, macOS, or Linux
- **Memory**: 512MB+ available RAM (scales with infrastructure size)

### Checkmk Requirements
- **Version**: Checkmk 2.4.0 or higher
- **API Access**: REST API must be enabled
- **User Account**: Automation user with appropriate monitoring permissions

### AI Client
Choose one or more MCP-compatible clients:
- **Claude Desktop** (recommended for ease of use)
- **VS Code with Continue extension**
- **Custom MCP client**

## Step 1: Install the Agent

### 1.1 Clone the Repository
```bash
git clone https://github.com/jlk/checkmk_mcp_server
cd checkmk_mcp_server
```

### 1.2 Create Virtual Environment
```bash
# Create virtual environment
python -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### 1.3 Install Dependencies
```bash
pip install -r requirements.txt
```

## Step 2: Configure Checkmk Connection

### 2.1 Choose Your Configuration Method

**CHOOSE ONE CONFIGURATION METHOD - Do not use both together:**

| Configuration Method | Best For | When to Use |
|---------------------|----------|-------------|
| **🔧 YAML Configuration** | Most users, new users | Development, complex setups, need comments |
| **⚙️ Environment Variables** | Production, containers | Docker, CI/CD, secret management systems |

#### Quick Decision Guide:
- **New to this project?** → Use YAML Configuration
- **Deploying with Docker/Kubernetes?** → Use Environment Variables  
- **Need advanced features (caching, batching)?** → Use YAML Configuration
- **Using external secret management?** → Use Environment Variables

**⚠️ Important**: Using both methods creates confusion. Environment variables always override YAML settings when both exist.

### 2.2 Method A: YAML Configuration File (Recommended for Most Users)

#### Create Configuration File
```bash
# Copy the example configuration
cp examples/configs/development.yaml config.yaml
```

#### Edit Configuration
Open `config.yaml` in your preferred editor:

```yaml
checkmk:
  server_url: "https://your-checkmk-server.com"
  username: "automation_user"
  password: "your_secure_password"
  site: "mysite"

llm:
  # Optional -- only used by the DIRECT CLI (checkmk_mcp_server/cli.py) for
  # natural-language command parsing. NOT used by the MCP server or the MCP
  # CLI (checkmk_cli_mcp.py): in the MCP setup, the AI client (e.g. Claude
  # Desktop) is the LLM, and the MCP CLI uses keyword matching only.
  # Option 1: OpenAI
  # openai_api_key: "sk-your-openai-api-key"
  # default_model: "gpt-3.5-turbo"
  
  # Option 2: Anthropic (recommended)
  anthropic_api_key: "sk-ant-your-api-key"
  default_model: "claude-3-5-sonnet-20241022"

# Advanced features (optional)
advanced_features:
  caching:
    max_size: 1000
    default_ttl: 300
  
  batch_processing:
    max_concurrent: 10
    rate_limit: 50
```

### 2.3 Method B: Environment Variables (Production/Containers)

#### Create Environment File
```bash
# Copy the example environment file
cp .env.example .env
```

#### Edit Environment Variables
Open `.env` in your preferred editor:

```bash
# Checkmk Configuration
CHECKMK_SERVER_URL=https://your-checkmk-server.com
CHECKMK_USERNAME=automation_user
CHECKMK_PASSWORD=your_secure_password
CHECKMK_SITE=mysite

# LLM Configuration (optional)
OPENAI_API_KEY=sk-your-openai-api-key
# Or use Anthropic:
# ANTHROPIC_API_KEY=your-anthropic-api-key

# Advanced settings (optional)
MAX_RETRIES=3
REQUEST_TIMEOUT=30
LOG_LEVEL=INFO
```

**⚠️ Limitation**: Advanced features like caching, batch processing, and UI customization require YAML configuration. Environment variables only support basic Checkmk connection settings.

### 2.4 Checkmk User Setup

Create an automation user in Checkmk with these permissions:
- **General**: Read access to monitoring data
- **Monitoring**: View all hosts and services
- **Setup**: Read access to configuration (for parameter management)

In Checkmk Web UI:
1. Go to **Setup → Users → Users**
2. Create new user with role **Automation user**
3. Set a secure password
4. Note the username and password for configuration

### 2.5 Test Connection
```bash
# Test your configuration
python -c "
from checkmk_mcp_server.config import load_config
from checkmk_mcp_server.api_client import CheckmkClient

config = load_config('config.yaml')
client = CheckmkClient(config.checkmk)
result = client.get_version_info()
print(f'Connected to Checkmk {result.get(\"versions\", {}).get(\"checkmk\", \"unknown\")}')
"
```

## Step 3: Start the MCP Server

### 3.1 Run the Server
```bash
python mcp_checkmk_server.py --config config.yaml
```

You should see output like:
```
INFO:checkmk_mcp_server.mcp_server:Starting Checkmk MCP Server
INFO:checkmk_mcp_server.mcp_server:Loaded configuration from config.yaml
INFO:checkmk_mcp_server.mcp_server:Registered 37 monitoring tools
INFO:checkmk_mcp_server.mcp_server:MCP server ready for connections
```

### 3.2 Verify Server Health
In another terminal:
```bash
# Test server responsiveness
python checkmk_cli_mcp.py hosts list --limit 5
```

This should return a list of hosts from your Checkmk server.

## Step 4: Connect AI Clients

### 4.1 Claude Desktop Setup

#### Install Claude Desktop
Download and install Claude Desktop from Anthropic's website.

#### Configure MCP Server
1. Locate your Claude Desktop configuration file:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

2. Add the Checkmk MCP server configuration:
```json
{
  "mcpServers": {
    "checkmk": {
      "command": "/full/path/to/checkmk_mcp_server/venv/bin/python",
      "args": [
        "/full/path/to/checkmk_mcp_server/mcp_checkmk_server.py",
        "--config",
        "/full/path/to/checkmk_mcp_server/config.yaml"
      ],
      "env": {
        "PYTHONPATH": "/full/path/to/checkmk_mcp_server"
      }
    }
  }
}
```

**Important**: Use absolute paths, not relative paths.

#### Test Connection
1. Restart Claude Desktop
2. Start a new conversation
3. Try: "Can you list the available Checkmk monitoring tools?"

You should see Claude respond with information about the 37 available monitoring tools.

### 4.2 VS Code with Continue Extension

#### Install Continue Extension
1. Open VS Code
2. Install the Continue extension from the marketplace

#### Configure MCP Server
1. Open Continue settings (Ctrl/Cmd + Shift + P → "Continue: Open Config")
2. Add to your `config.json`:

```json
{
  "models": [
    {
      "title": "Claude 3.5 Sonnet",
      "provider": "anthropic",
      "model": "claude-3-5-sonnet-20241022",
      "apiKey": "your-anthropic-api-key"
    }
  ],
  "mcpServers": [
    {
      "name": "checkmk",
      "command": "python",
      "args": [
        "/full/path/to/checkmk_mcp_server/mcp_checkmk_server.py",
        "--config",
        "/full/path/to/checkmk_mcp_server/config.yaml"
      ]
    }
  ]
}
```

#### Test Connection
1. Restart VS Code
2. Open Continue chat
3. Ask: "Show me critical monitoring problems"

### 4.3 Alternative: CLI Interface

For testing or environments without MCP clients. Note: the MCP CLI does not
use an LLM — its interactive mode understands a fixed set of keyword
patterns (e.g. "list all hosts"), not free-form natural language. Full
natural-language interaction requires an AI client like Claude Desktop:

```bash
# Interactive mode
python checkmk_cli_mcp.py interactive

# Direct commands
python checkmk_cli_mcp.py hosts list
python checkmk_cli_mcp.py status overview
python checkmk_cli_mcp.py services list server01
```

## Step 5: First Monitoring Queries

### 5.1 Basic Infrastructure Health
Try these natural language queries in your AI client:

**Get overall status**:
> "Show me the current health status of my infrastructure"

**Find problems**:
> "What critical problems do I have right now?"

**Host information**:
> "List all hosts in my environment"

### 5.2 Service Management
**Service status**:
> "Show me services for server01"

**Acknowledge problems**:
> "Acknowledge the CPU load problem on server01 with comment 'investigating high load'"

**Schedule maintenance**:
> "Create a 2-hour downtime for database maintenance on prod-db-01"

### 5.3 Performance Analysis
**Metrics and trends**:
> "Show me CPU performance for web-server-01 over the last 24 hours"

**Historical data**:
> "Get disk usage trends for the database servers this week"

**Event history**:
> "What events occurred on server01 related to disk space?"

## Step 6: Advanced Configuration

### 6.1 Alternative Configuration Examples

#### Using Environment Variables in Production
If you chose environment variables (Method B), here's how to use them in production:

```bash
# .env file
CHECKMK_SERVER_URL=https://your-checkmk-server.com
CHECKMK_USERNAME=automation_user
CHECKMK_PASSWORD=your_secure_password
CHECKMK_SITE=production
```

Or set directly in shell (good for containers)
```bash
export CHECKMK_SERVER_URL=https://your-checkmk-server.com
export CHECKMK_USERNAME=automation_user
export CHECKMK_PASSWORD=your_secure_password
export CHECKMK_SITE=production
```

After either way, call
```bash
python mcp_checkmk_server.py
```
#### Hybrid Approach: YAML + Environment Variable Overrides (Advanced)
For advanced users who need complex configuration but want environment-based secrets:

```yaml
# config.yaml - Non-sensitive settings with placeholders
checkmk:
  server_url: "https://staging-server.com"  # Will be overridden by env var
  username: "automation_user"               # Will be overridden by env var
  # password: leave empty, use env var only
  site: "production"

advanced_features:
  caching:
    max_size: 10000
    default_ttl: 600
```

```bash
# Set only sensitive values as environment variables
export CHECKMK_SERVER_URL=https://production-server.com
export CHECKMK_PASSWORD=secure_production_password
python mcp_checkmk_server.py --config config.yaml
```

**Use this approach when**: You need advanced YAML features but want secure credential management.

### 6.2 Production Configuration
For production environments, adjust these settings in `config.yaml`:

```yaml
advanced_features:
  caching:
    max_size: 10000      # Larger cache for better performance
    default_ttl: 600     # 10-minute cache TTL
  
  batch_processing:
    max_concurrent: 20   # Higher concurrency
    rate_limit: 100      # Higher rate limit
  
  metrics:
    retention_hours: 48  # Longer metrics retention
  
  recovery:
    circuit_breaker:
      failure_threshold: 10
      recovery_timeout: 30
```

### 6.3 Security Considerations
- Use strong passwords for automation users
- Limit Checkmk user permissions to required minimum
- Store credentials in secure vaults for production
- Enable HTTPS for all Checkmk API communications
- Consider network security (firewalls, VPNs)

## Troubleshooting

### Common Issues

**MCP server won't start**:
- Check Python version (3.8+ required)
- Verify all dependencies installed
- Check configuration file syntax

**Can't connect to Checkmk**:
- Verify server URL is accessible
- Check username/password
- Ensure REST API is enabled in Checkmk
- Test with curl: `curl -k https://your-server/check_mk/api/1.0/version`

**AI client can't connect**:
- Ensure absolute paths in configuration
- Check MCP server is running
- Verify no firewall blocking connections
- Check logs for specific error messages

For detailed troubleshooting, see the [Troubleshooting Guide](troubleshooting.md).

## Next Steps

### Learn More
- **[Usage Examples](USAGE_EXAMPLES.md)** - Practical examples and common workflows
- **[Architecture Guide](architecture.md)** - Technical implementation details
- **[Advanced Features](ADVANCED_FEATURES.md)** - Streaming, caching, batch operations
- **[Parameter Management](PARAMETER_MANAGEMENT_GUIDE.md)** - Service parameter configuration

### Explore Features
- Try different natural language queries from [Usage Examples](USAGE_EXAMPLES.md)
- Explore [historical data scraping](historical_scraping_examples.md)
- Set up business intelligence monitoring
- Learn about [specialized parameter handlers](ADVANCED_FEATURES.md#specialized-parameter-handlers)

### Need Help?
- Check the [Troubleshooting Guide](troubleshooting.md) for common issues
- Browse the [complete documentation index](README.md)

## Support

If you encounter issues:
1. Check the [troubleshooting guide](troubleshooting.md)
2. Review [existing GitHub issues](../../issues)
3. Create a new issue with:
   - Your operating system and Python version
   - Checkmk version
   - Complete error messages
   - Steps to reproduce the issue

Welcome to conversational infrastructure monitoring!