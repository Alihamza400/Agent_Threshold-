# =====================================================================
# AgentThreshold — Staging Environment
# =====================================================================

environment   = "staging"
aws_region    = "us-east-1"
cluster_name  = "agentthreshold-cluster"

# VPC
vpc_cidr            = "10.10.0.0/16"
availability_zones  = ["us-east-1a", "us-east-1b", "us-east-1c"]
private_subnet_cidrs = ["10.10.1.0/24", "10.10.2.0/24", "10.10.3.0/24"]
public_subnet_cidrs  = ["10.10.101.0/24", "10.10.102.0/24", "10.10.103.0/24"]

# EKS — production-like but scaled down
cluster_version       = "1.30"
node_instance_types   = ["t3.large"]
node_desired_size     = 2
node_min_size         = 2
node_max_size         = 6
node_disk_size        = 50

# RDS — single-AZ, mid-tier instance
db_instance_class        = "db.t3.small"
db_allocated_storage     = 50
db_max_allocated_storage = 100
db_multi_az              = false
db_backup_retention_period = 3

# ElastiCache — single node, TLS enabled
redis_node_type        = "cache.t3.small"
redis_num_cache_nodes  = 1
redis_at_rest_encryption_enabled  = true
redis_transit_encryption_enabled  = true
