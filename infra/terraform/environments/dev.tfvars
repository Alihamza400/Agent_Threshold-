# =====================================================================
# AgentThreshold — Dev Environment
# =====================================================================

environment   = "dev"
aws_region    = "us-east-1"
cluster_name  = "agentthreshold-cluster"

# VPC
vpc_cidr            = "10.0.0.0/16"
availability_zones  = ["us-east-1a", "us-east-1b", "us-east-1c"]
private_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
public_subnet_cidrs  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

# EKS — minimal for dev
cluster_version       = "1.30"
node_instance_types   = ["t3.medium"]
node_desired_size     = 2
node_min_size         = 1
node_max_size         = 4
node_disk_size        = 30

# RDS — single-AZ, smallest instance
db_instance_class        = "db.t3.micro"
db_allocated_storage     = 20
db_max_allocated_storage = 50
db_multi_az              = false
db_backup_retention_period = 1

# ElastiCache — single node, no replication
redis_node_type        = "cache.t3.micro"
redis_num_cache_nodes  = 1
redis_at_rest_encryption_enabled  = true
redis_transit_encryption_enabled  = false
