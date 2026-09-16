# =====================================================================
# AgentThreshold — Outputs
# =====================================================================

# ---------------------------------------------------------------------------
# VPC
# ---------------------------------------------------------------------------
output "vpc_id" {
  description = "ID of the VPC"
  value       = module.vpc.vpc_id
}

output "private_subnets" {
  description = "IDs of the private subnets"
  value       = module.vpc.private_subnets
}

output "public_subnets" {
  description = "IDs of the public subnets"
  value       = module.vpc.public_subnets
}

# ---------------------------------------------------------------------------
# EKS
# ---------------------------------------------------------------------------
output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "cluster_ca_certificate" {
  description = "EKS cluster CA certificate (base64-encoded)"
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "cluster_oidc_issuer_url" {
  description = "OIDC issuer URL for IRSA"
  value       = module.eks.cluster_oidc_issuer_url
}

output "node_security_group_id" {
  description = "Security group ID attached to EKS worker nodes"
  value       = module.eks.node_security_group_id
}

# ---------------------------------------------------------------------------
# RDS PostgreSQL
# ---------------------------------------------------------------------------
output "db_endpoint" {
  description = "RDS PostgreSQL connection endpoint"
  value       = module.db.db_instance_address
}

output "db_port" {
  description = "RDS PostgreSQL port"
  value       = module.db.db_instance_port
}

output "db_name" {
  description = "RDS database name"
  value       = module.db.db_name
}

output "db_arn" {
  description = "RDS instance ARN"
  value       = module.db.db_instance_arn
}

# ---------------------------------------------------------------------------
# ElastiCache Redis
# ---------------------------------------------------------------------------
output "redis_endpoint" {
  description = "Redis primary endpoint"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "redis_port" {
  description = "Redis port"
  value       = aws_elasticache_replication_group.main.port
}

output "redis_arn" {
  description = "Redis replication group ARN"
  value       = aws_elasticache_replication_group.main.arn
}

# ---------------------------------------------------------------------------
# KMS
# ---------------------------------------------------------------------------
output "kms_key_arn" {
  description = "ARN of the KMS encryption key"
  value       = aws_kms_key.main.arn
}

# ---------------------------------------------------------------------------
# Secrets Manager
# ---------------------------------------------------------------------------
output "db_credentials_secret_arn" {
  description = "ARN of the DB credentials secret in Secrets Manager"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "redis_credentials_secret_arn" {
  description = "ARN of the Redis credentials secret in Secrets Manager"
  value       = aws_secretsmanager_secret.redis_credentials.arn
}
