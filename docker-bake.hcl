# Docker Bake — build every AgentThreshold service image from the shared
# parametrized Dockerfile.
#
#   docker buildx bake            # all services
#   docker buildx bake api-gateway
#   docker buildx bake --print    # show resolved targets
#
# Registry image names are set per environment (see CI).

group "default" {
  targets = [
    "api-gateway",
    "notification",
    "execution",
    "audit-service",
    "mcp-server",
    "orchestrator",
  ]
}

target "api-gateway" {
  dockerfile = "Dockerfile"
  args = {
    PACKAGE    = "at-api-gateway"
    APP_MODULE = "app.main:app"
  }
  tags = ["agentthreshold/api-gateway:latest"]
}

target "notification" {
  dockerfile = "Dockerfile"
  args = {
    PACKAGE    = "at-notification"
    APP_MODULE = "notification_service.main:app"
  }
  tags = ["agentthreshold/notification:latest"]
}

target "execution" {
  dockerfile = "Dockerfile"
  args = {
    PACKAGE    = "at-execution"
    APP_MODULE = "execution_service.main:app"
  }
  tags = ["agentthreshold/execution:latest"]
}

target "audit-service" {
  dockerfile = "Dockerfile"
  args = {
    PACKAGE    = "at-audit-service"
    APP_MODULE = "audit_service.main:app"
  }
  tags = ["agentthreshold/audit-service:latest"]
}

target "mcp-server" {
  dockerfile = "Dockerfile"
  args = {
    PACKAGE    = "at-mcp-server"
    APP_MODULE = "mcp_server.main:app"
  }
  tags = ["agentthreshold/mcp-server:latest"]
}

target "orchestrator" {
  dockerfile = "Dockerfile"
  args = {
    PACKAGE    = "at-orchestrator"
    APP_MODULE = "orchestrator.main:app"
  }
  tags = ["agentthreshold/orchestrator:latest"]
}