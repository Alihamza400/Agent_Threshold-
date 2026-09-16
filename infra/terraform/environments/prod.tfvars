# =====================================================================
# AgentThreshold — Production Environment
# =====================================================================

environment   = "prod"
aws_region    = "us-east-1"
cluster_name  = "agentthreshold-cluster"

# VPC — production CIDR block
vpc_cidr            = "10.20.0.0/16"
availability_zones  = ["us-east-1a", "us-east-1b", "us-east-1c"]
private_subnet_cidrs = ["10.20.1.0/24", "10.20.2.0/24", "10.20.3.0/24"]
public_subnet_cidrs  = ["10.20.101.0/24", "10.20.102.0/24", "10.20.103.0/24"]

# EKS — production nodes
cluster_version       = "1.30"
node_instance_types   = ["m5.xlarge"]
node_desired_size     = 3
node_min_size         = 3
node_max_size         = 10
node_disk_size        = 100

# RDS — Multi-AZ, production instance, full backup retention
db_instance_class        = "db.r6g.large"
db_allocated_storage     = 100
db_max_allocated_storage = 500
db_multi_az              = true
db_backup_retention_period = 14

# ElastiCache — replicated cluster, full encryption
redis_node_type        = "cache.r6g.large"
redis_num_cache_nodes  = 2
redis_at_rest_encryption_enabled  = true
redis_transit_encryption_enabled  = true

# KMS
kms_key_deletion_window = 30
kms_key_enable_rotation = true
