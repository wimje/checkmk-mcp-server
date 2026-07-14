# Troubleshooting Guide

This guide helps resolve common issues when setting up and using the Checkmk MCP Server.

## Quick Diagnosis

### Is the MCP Server Running?
```bash
# With YAML configuration
python mcp_checkmk_server.py --config config.yaml

# With environment variables
python mcp_checkmk_server.py

# You should see:
# INFO:checkmk_mcp_server.mcp_server:Starting Checkmk MCP Server
# INFO:checkmk_mcp_server.mcp_server:Registered 37 monitoring tools
# INFO:checkmk_mcp_server.mcp_server:MCP server ready for connections
```

### Can You Connect to Checkmk?
```bash
# Test direct API access
curl -k https://your-checkmk-server/check_mk/api/1.0/version

# Test through the agent (YAML config)
python -c "
from checkmk_mcp_server.config import load_config
from checkmk_mcp_server.api_client import CheckmkAPIClient
config = load_config('config.yaml')
client = CheckmkAPIClient(config)
print(client.get_version())
"

# Test through the agent (environment variables)
python -c "
from checkmk_mcp_server.config import load_config
from checkmk_mcp_server.api_client import CheckmkAPIClient
config = load_config()  # Auto-loads from environment
client = CheckmkAPIClient(config)
print(client.get_version())
"
```

### Can Your AI Client Connect?
Try this natural language query in your AI client:
> "List the available Checkmk monitoring tools"

If this works, your setup is correct.

## Installation Issues

### Python Version Problems

**Error**: `SyntaxError` or `ModuleNotFoundError`

**Cause**: Python version too old (need 3.8+)

**Solution**:
```bash
# Check Python version
python --version

# If < 3.8, install newer Python
# macOS with Homebrew:
brew install python@3.11

# Ubuntu/Debian:
sudo apt update && sudo apt install python3.11 python3.11-venv

# Create venv with specific Python version
python3.11 -m venv venv
```

### Dependency Installation Failures

**Error**: `pip install` fails with compilation errors

**Common causes and solutions**:

1. **Missing system dependencies**:
```bash
# Ubuntu/Debian:
sudo apt install build-essential python3-dev

# CentOS/RHEL:
sudo yum groupinstall "Development Tools"
sudo yum install python3-devel

# macOS:
xcode-select --install
```

2. **Outdated pip**:
```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

3. **Network/proxy issues**:
```bash
# Use different index
pip install -r requirements.txt -i https://pypi.org/simple/

# With proxy
pip install -r requirements.txt --proxy http://proxy:port
```

### Virtual Environment Issues

**Error**: `command not found` after activation

**Solution**:
```bash
# Ensure you're in the right directory
cd checkmk_llm_agent

# Recreate virtual environment
rm -rf venv
python -m venv venv

# Activate (verify prompt changes)
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate     # Windows

# Verify activation
which python  # Should show venv path
```

## Configuration Issues

### Configuration File Not Found

**Error**: `FileNotFoundError: config.yaml not found`

**For YAML Configuration**:
```bash
# Check file exists
ls -la config.yaml

# Copy from example
cp examples/configs/development.yaml config.yaml

# Use absolute path
python mcp_checkmk_server.py --config /full/path/to/config.yaml
```

**For Environment Variables**:
```bash
# Check .env file exists
ls -la .env

# Copy from example
cp .env.example .env

# Or set environment variables directly
export CHECKMK_SERVER_URL="https://your-server.com"
export CHECKMK_USERNAME="your_user"  
export CHECKMK_PASSWORD="your_password"
export CHECKMK_SITE="your_site"

# Run without config file
python mcp_checkmk_server.py
```

### Invalid Configuration Format

**Error**: `yaml.scanner.ScannerError` or similar YAML errors (YAML configuration only)

**Solution**:
```bash
# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('config.yaml'))"

# Common issues:
# 1. Indentation (use spaces, not tabs)
# 2. Missing quotes around URLs with special characters
# 3. Unescaped special characters in passwords
```

**Example fix**:
```yaml
# Wrong:
password: P@ssw0rd!  # ! has special meaning in YAML

# Right:
password: "P@ssw0rd!"
```

### Environment Variables Not Loaded

**Error**: Configuration values not being read despite setting environment variables

**Solutions**:
```bash
# Verify environment variables are set
env | grep CHECKMK_

# Check for typos in variable names (case-sensitive)
echo $CHECKMK_SERVER_URL
echo $CHECKMK_USERNAME

# Ensure .env file is in the correct directory
ls -la .env

# Source .env file manually if needed
source .env

# Check that no config.yaml exists (env vars have lower priority)
ls -la config.yaml
```

### Checkmk Connection Issues

**Error**: Connection timeout, authentication failed

**Diagnosis steps**:

1. **Check server accessibility**:
```bash
# Basic connectivity
ping your-checkmk-server.com

# HTTPS access
curl -k https://your-checkmk-server.com

# API endpoint
curl -k https://your-checkmk-server.com/check_mk/api/1.0/version
```

2. **Verify API is enabled**:
   - In Checkmk Web UI: Setup → General → Global settings → User interface
   - Ensure "Web API" is enabled

3. **Check credentials**:
```bash
# Test authentication
curl -k -u "username:password" \
  https://your-checkmk-server.com/check_mk/api/1.0/version
```

4. **Common fixes**:
   - Use automation user, not regular user
   - Check site name (case-sensitive)
   - Verify user has monitoring permissions
   - Check if using HTTPS with self-signed certificates

### SSL/TLS Certificate Issues

**Error**: `SSL: CERTIFICATE_VERIFY_FAILED`

**Solutions**:

1. **For development (not recommended for production)**:
```yaml
checkmk:
  server_url: "https://your-server.com"
  verify_ssl: false  # Add this line
```

2. **For production with self-signed certificates**:
```bash
# Download certificate
openssl s_client -showcerts -connect your-server.com:443 \
  </dev/null 2>/dev/null | openssl x509 -outform PEM > checkmk.crt

# Add to config
checkmk:
  server_url: "https://your-server.com"
  ca_cert_path: "checkmk.crt"
```

## LLM Configuration Issues

### Wrong Model Provider

**Error**: `Invalid model` or `Model not found`

**Common issues**:
1. Using OpenAI model with Anthropic API key or vice versa
2. Incorrect model name format

**Solutions**:

For **Anthropic/Claude**:
```yaml
llm:
  anthropic_api_key: "sk-ant-your-key"
  # Correct model names for Anthropic
  default_model: "claude-3-5-sonnet-20241022"  # Latest Sonnet
  # default_model: "claude-3-opus-20240229"     # Opus (most capable)
  # default_model: "claude-3-haiku-20240307"    # Haiku (fastest/cheapest)
```

For **OpenAI**:
```yaml
llm:
  openai_api_key: "sk-your-key"
  # Correct model names for OpenAI
  default_model: "gpt-4"                # GPT-4
  # default_model: "gpt-4-turbo"        # GPT-4 Turbo
  # default_model: "gpt-3.5-turbo"      # GPT-3.5 (faster/cheaper)
```

### API Key Issues

**Error**: `Authentication failed` or `Invalid API key`

**Diagnosis**:
```bash
# Check if API key is set
echo $OPENAI_API_KEY
echo $ANTHROPIC_API_KEY

# Test Anthropic API directly
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model": "claude-3-haiku-20240307", "max_tokens": 10, "messages": [{"role": "user", "content": "Hi"}]}'

# Test OpenAI API directly  
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

**Common fixes**:
- Ensure API key starts with correct prefix (`sk-` for OpenAI, `sk-ant-` for Anthropic)
- Check API key has not expired
- Verify billing/credits are available on your account
- Make sure you're using the right provider's key with the right model

## MCP Connection Issues

### MCP Client Hangs on Connection

**Error**: Client hangs indefinitely during initialization

**Known cause**: MCP SDK 1.12.0 issue on macOS with Python 3.12

**Solutions**:

1. **Use different Python version**:
```bash
# Install Python 3.11
pyenv install 3.11.7
pyenv local 3.11.7

# Recreate environment
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Use timeout wrapper** (already implemented):
   The agent includes a 30-second timeout for connections

3. **Alternative: Use direct CLI**:
```bash
# Instead of MCP client
python -m checkmk_mcp_server.cli --config config.yaml hosts list
```

### Claude Desktop Connection Issues

**Error**: Claude Desktop doesn't recognize MCP server

**Diagnosis**:
1. Check configuration file location:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

2. **Verify configuration syntax**:
```json
{
  "mcpServers": {
    "checkmk": {
      "command": "python",
      "args": [
        "/absolute/path/to/mcp_checkmk_server.py",
        "--config",
        "/absolute/path/to/config.yaml"
      ]
    }
  }
}
```

**Common fixes**:
- Use absolute paths (not relative or `~`)
- Ensure Python is in PATH or use full Python path
- Restart Claude Desktop after configuration changes
- Check server logs for startup errors

### VS Code MCP Connection Issues

**Error**: Continue extension can't connect to MCP server

**Solutions**:
1. **Check Continue configuration**:
   - Open Command Palette: Ctrl/Cmd + Shift + P
   - Run "Continue: Open Config"
   - Verify MCP server configuration

2. **Restart VS Code** after configuration changes

3. **Check extension logs**:
   - View → Output → Select "Continue" from dropdown

## Runtime Issues

### High Memory Usage

**Symptom**: Agent consumes excessive memory

**Causes and solutions**:

1. **Large datasets without streaming**:
```yaml
# Enable streaming for large environments
advanced_features:
  streaming:
    default_batch_size: 100  # Reduce if needed
    max_concurrent_batches: 5
```

2. **Cache size too large**:
```yaml
advanced_features:
  caching:
    max_size: 1000  # Reduce from default
    default_ttl: 300
```

3. **Too many concurrent operations**:
```yaml
advanced_features:
  batch_processing:
    max_concurrent: 5  # Reduce from default
    rate_limit: 25
```

### Slow Performance

**Symptom**: Queries take a long time to complete

**Optimizations**:

1. **Enable caching**:
```yaml
advanced_features:
  caching:
    max_size: 5000     # Increase cache size
    default_ttl: 600   # Longer cache TTL
```

2. **Use filtering**:
```bash
# Instead of listing all hosts
python checkmk_cli_mcp.py hosts list

# Filter to reduce data
python checkmk_cli_mcp.py hosts list --search "web*" --limit 50
```

3. **Network optimization**:
   - Use local network connection to Checkmk
   - Check for network latency issues
   - Consider running agent on same network as Checkmk

### API Rate Limiting

**Error**: `HTTP 429 Too Many Requests`

**Solutions**:

1. **Reduce request rate**:
```yaml
advanced_features:
  batch_processing:
    rate_limit: 10     # Reduce from 50
    max_concurrent: 2  # Reduce concurrent requests
```

2. **Add delays between requests**:
```yaml
advanced_features:
  recovery:
    retry:
      base_delay: 2.0  # Increase delay
      max_retries: 5
```

3. **Use caching to reduce API calls**:
```yaml
advanced_features:
  caching:
    max_size: 10000
    default_ttl: 1200  # 20-minute cache
```

### Permission Errors

**Error**: `HTTP 403 Forbidden` or permission denied

**Solutions**:

1. **Check user permissions in Checkmk**:
   - User must have monitoring read permissions
   - For parameter management: setup read/write permissions
   - For host management: admin permissions required

2. **Use appropriate user role**:
   - Monitoring: Use "Automation user" role
   - Administration: Use "Administrator" role

3. **Verify site access**:
   - Check user has access to the specified site
   - Verify site name in configuration

## Debugging Tips

### Enable Debug Logging

```python
# Add to your config.yaml
logging:
  level: DEBUG
  file: "debug.log"
```

Or set environment variable:
```bash
export CHECKMK_AGENT_DEBUG=1
python mcp_checkmk_server.py --config config.yaml
```

### Test Individual Components

**Test API client**:
```python
from checkmk_mcp_server.api_client import CheckmkAPIClient
from checkmk_mcp_server.config import load_config

config = load_config('config.yaml')
client = CheckmkAPIClient(config)

# Test basic connectivity
print(client.get_version())

# Test host listing
hosts = client.list_hosts(limit=5)
print(f"Found {len(hosts)} hosts")
```

**Test MCP server tools**:
```bash
# List available tools
python checkmk_cli_mcp.py --help

# Test specific tool
python checkmk_cli_mcp.py hosts list --limit 3
```

### Check System Resources

```bash
# Memory usage
ps aux | grep python

# Network connectivity
netstat -an | grep :443

# Disk space
df -h

# Check open files (if hitting limits)
lsof | grep python | wc -l
```

## Common Error Messages

### "ModuleNotFoundError: No module named 'checkmk_mcp_server'"

**Solution**: Ensure you're in the correct directory and virtual environment is activated:
```bash
cd checkmk_mcp_server
source venv/bin/activate
export PYTHONPATH=$PWD:$PYTHONPATH
```

### "NameError: name 'ExceptionGroup' is not defined"

Seen when starting `mcp_checkmk_server.py` on Python 3.10 or older with a version of the code before 2026-07-14. `ExceptionGroup` is a builtin only in Python 3.11+.

**Solution**: Update to the current code, which includes a compatibility shim using the `exceptiongroup` backport. Alternatively, run with Python 3.11+.

### "NameError: name 'MCPCLIContext' is not defined"

Seen when starting `checkmk_cli_mcp.py` with a version of the code before 2026-07-14 — a type annotation referenced a class before its definition.

**Solution**: Update to the current code (fixed via `from __future__ import annotations` in `checkmk_mcp_server/cli_mcp.py`).

### "cannot import name 'CheckmkAPIClient'"

The API client class is named `CheckmkClient`, not `CheckmkAPIClient`, and takes the `checkmk` section of the config:

```python
from checkmk_mcp_server.config import load_config
from checkmk_mcp_server.api_client import CheckmkClient

config = load_config('config.yaml')
client = CheckmkClient(config.checkmk)
client.test_connection()  # True if reachable
```

### "yaml.scanner.ScannerError"

**Solution**: Fix YAML syntax in config.yaml:
- Use consistent indentation (spaces, not tabs)
- Quote values with special characters
- Check for missing colons or incorrect nesting

### "requests.exceptions.ConnectionError"

**Solution**: Network connectivity issue:
- Check server URL is correct
- Verify network connectivity
- Check firewall/proxy settings
- Ensure Checkmk server is running

### "TypeError: 'NoneType' object is not subscriptable"

**Solution**: Usually indicates missing or invalid configuration:
- Check all required config fields are present
- Verify data types match expected values
- Enable debug logging to see detailed error

## Getting Help

If these solutions don't resolve your issue:

1. **Check GitHub Issues**: [Existing issues](../../issues)

2. **Create a new issue** with:
   - Operating system and Python version
   - Checkmk version
   - Complete error messages
   - Steps to reproduce
   - Configuration (remove sensitive data)

3. **Include debug information**:
```bash
# System info
python --version
pip list | grep -E "(mcp|checkmk|pydantic|httpx)"

# Test connection
curl -k https://your-checkmk-server/check_mk/api/1.0/version

# Configuration (sanitized)
cat config.yaml | sed 's/password:.*/password: [REDACTED]/'
```

4. **Check logs**:
   - Enable debug logging
   - Include relevant log entries (remove sensitive data)

The Checkmk MCP Server community is ready to help!

## Related Documentation

- **[Getting Started Guide](getting-started.md)** - Initial setup procedures
- **[Migration Guide](migration.md)** - Upgrading from older Checkmk versions
- **[Usage Examples](USAGE_EXAMPLES.md)** - Working examples and workflows
- **[Architecture Guide](architecture.md)** - Technical implementation details
- **[Advanced Features](ADVANCED_FEATURES.md)** - Performance optimization guides