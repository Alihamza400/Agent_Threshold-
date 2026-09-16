# =====================================================================
# AgentThreshold — Root Module
# VPC · EKS · RDS PostgreSQL 16 · ElastiCache Redis 7
# =====================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
  name_prefix = "${var.project}-${var.environment}"
}

# ---------------------------------------------------------------------------
# KMS — encryption key for RDS, EKS secrets, and ElastiCache
# ---------------------------------------------------------------------------
resource "aws_kms_key" "main" {
  description             = "KMS key for ${local.name_prefix}"
  deletion_window_in_days = var.kms_key_deletion_window
  enable_key_rotation     = var.kms_key_enable_rotation

  tags = { Name = "${local.name_prefix}-kms" }
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name_prefix}"
  target_key_id = aws_kms_key.main.key_id
}

# ---------------------------------------------------------------------------
# VPC
# ---------------------------------------------------------------------------
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.8"

  name = "${local.name_prefix}-vpc"
  cidr = var.vpc_cidr
  azs  = var.availability_zones

  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway   = true
  single_nat_gateway   = var.environment != "prod"
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tags required by EKS for subnet auto-discovery
  public_subnet_tags = {
    "kubernetes.io/role/elb"                                            = 1
    "kubernetes.io/cluster/${var.cluster_name}-${var.environment}"      = "shared"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"                                   = 1
    "kubernetes.io/cluster/${var.cluster_name}-${var.environment}"      = "shared"
  }

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

# ---------------------------------------------------------------------------
# EKS Cluster
# ---------------------------------------------------------------------------
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.11"

  cluster_name    = "${var.cluster_name}-${var.environment}"
  cluster_version = var.cluster_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  # Encryption
  cluster_encryption_config = {
    provider_key_arn = aws_kms_key.main.arn
    resources        = ["secrets"]
  }

  # Logging
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  # Managed node groups
  eks_managed_node_groups = {
    default = {
      name = "${local.name_prefix}-nodes"

      instance_types = var.node_instance_types
      capacity_type  = var.environment == "prod" ? "ON_DEMAND" : "SPOT"

      min_size     = var.node_min_size
      max_size     = var.node_max_size
      desired_size = var.node_desired_size

      disk_size = var.node_disk_size

      labels = {
        Environment = var.environment
        NodeType    = "default"
      }

      tags = {
        Name = "${local.name_prefix}-node-group"
      }
    }
  }

  # OIDC provider for IRSA
  enable_irsa = true

  tags = {
    Name = "${local.name_prefix}-eks"
  }
}

# ---------------------------------------------------------------------------
# RDS PostgreSQL 16
# ---------------------------------------------------------------------------
module "db_security_group" {
  source  = "terraform-aws-modules/security-group/aws"
  version = "~> 5.1"

  name        = "${local.name_prefix}-rds-sg"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = module.vpc.vpc_id

  ingress_with_source_security_group_id = [
    {
      rule                     = "postgresql-tcp"
      source_security_group_id = module.eks.node_security_group_id
    }
  ]

  egress_rules = ["all-all"]

  tags = { Name = "${local.name_prefix}-rds-sg" }
}

module "db" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.7"

  identifier = "${local.name_prefix}-postgres"

  engine               = "postgres"
  engine_version       = var.db_engine_version
  instance_class       = var.db_instance_class
  allocated_storage    = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_type         = "gp3"
  storage_encrypted    = true
  kms_key_id           = aws_kms_key.main.arn

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  port     = var.db_port

  multi_az               = var.db_multi_az
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [module.db_security_group.security_group_id]

  backup_retention_period = var.db_backup_retention_period
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  performance_insights_enabled          = true
  performance_insights_kms_key_id       = aws_kms_key.main.arn
  performance_insights_retention_period = 7

  deletion_protection = var.environment == "prod"
  skip_final_snapshot = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${local.name_prefix}-final" : null

  parameters = [
    {
      name  = "rds.force_ssl"
      value = "1"
    },
    {
      name  = "log_statement"
      value = "all"
    },
    {
      name  = "log_min_duration_statement"
      value = "1000"
    }
  ]

  tags = { Name = "${local.name_prefix}-postgres" }
}

# ---------------------------------------------------------------------------
# ElastiCache Redis 7
# ---------------------------------------------------------------------------
module "redis_security_group" {
  source  = "terraform-aws-modules/security-group/aws"
  version = "~> 5.1"

  name        = "${local.name_prefix}-redis-sg"
  description = "Security group for ElastiCache Redis"
  vpc_id      = module.vpc.vpc_id

  ingress_with_source_security_group_id = [
    {
      rule                     = "redis-tcp"
      source_security_group_id = module.eks.node_security_group_id
    }
  ]

  egress_rules = ["all-all"]

  tags = { Name = "${local.name_prefix}-redis-sg" }
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.name_prefix}-redis"
  subnet_ids = module.vpc.private_subnets

  tags = { Name = "${local.name_prefix}-redis" }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "Redis 7 cluster for ${local.name_prefix}"

  node_type            = var.redis_node_type
  num_cache_clusters   = var.redis_num_cache_nodes
  port                 = var.redis_port
  parameter_group_name = var.redis_parameter_group_name
  engine_version       = var.redis_engine_version

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [module.redis_security_group.security_group_id]

  at_rest_encryption_enabled = var.redis_at_rest_encryption_enabled
  transit_encryption_enabled = var.redis_transit_encryption_enabled
  auth_token                = var.redis_transit_encryption_enabled ? var.redis_auth_token : null
  kms_key_id                = aws_kms_key.main.arn

  automatic_failover_enabled = var.redis_num_cache_nodes > 1
  multi_az_enabled           = var.redis_num_cache_nodes > 1

  snapshot_retention_limit = var.environment == "prod" ? 7 : 1
  snapshot_window          = "03:00-05:00"
  maintenance_window       = "sun:05:00-sun:07:00"

  tags = { Name = "${local.name_prefix}-redis" }
}

# ---------------------------------------------------------------------------
# Secrets Manager — DB credentials (managed separately from RDS resource)
# ---------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "db_credentials" {
  name        = "${local.name_prefix}/db-credentials"
  description = "PostgreSQL credentials for ${local.name_prefix}"
  kms_key_id  = aws_kms_key.main.arn

  tags = { Name = "${local.name_prefix}-db-credentials" }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = var.db_username
    password = var.db_password
    host     = module.db.db_instance_address
    port     = var.db_port
    dbname   = var.db_name
    url      = "postgresql+psycopg://${var.db_username}:${var.db_password}@${module.db.db_instance_address}:${var.db_port}/${var.db_name}"
  })
}

resource "aws_secretsmanager_secret" "redis_credentials" {
  name        = "${local.name_prefix}/redis-credentials"
  description = "Redis connection info for ${local.name_prefix}"
  kms_key_id  = aws_kms_key.main.arn

  tags = { Name = "${local.name_prefix}-redis-credentials" }
}

resource "aws_secretsmanager_secret_version" "redis_credentials" {
  secret_id = aws_secretsmanager_secret.redis_credentials.id
  secret_string = jsonencode({
    host = aws_elasticache_replication_group.main.primary_endpoint_address
    port = var.redis_port
    url  = "rediss://:${var.redis_auth_token}@${aws_elasticache_replication_group.main.primary_endpoint_address}:${var.redis_port}"
  })
}
