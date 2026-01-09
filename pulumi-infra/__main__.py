import json
import pulumi
import pulumi_aws as aws

# ---------------------------
# PULUMI CONFIG (IMPORTANT)
# ---------------------------
config = pulumi.Config()

APP_NAME = config.require("app_name")          # django2
AWS_REGION = config.get("aws_region") or "us-east-1"
CONTAINER_PORT = config.get_int("container_port") or 8000

# ---------------------------
# ECR Repository
# ---------------------------
repo = aws.ecr.Repository(
    f"{APP_NAME}-ecr",
    name=f"{APP_NAME}-ecr",
    force_delete=True
)

# ---------------------------
# ECS Cluster
# ---------------------------
cluster = aws.ecs.Cluster(f"{APP_NAME}-cluster")

# ---------------------------
# IAM ROLES
# ---------------------------
assume_role_policy = aws.iam.get_policy_document(
    statements=[{
        "actions": ["sts:AssumeRole"],
        "principals": [{
            "type": "Service",
            "identifiers": ["ecs-tasks.amazonaws.com"]
        }]
    }]
).json

execution_role = aws.iam.Role(
    f"{APP_NAME}-execution-role",
    assume_role_policy=assume_role_policy
)

aws.iam.RolePolicyAttachment(
    f"{APP_NAME}-execution-policy",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
)

task_role = aws.iam.Role(
    f"{APP_NAME}-task-role",
    assume_role_policy=assume_role_policy
)

# ---------------------------
# CLOUDWATCH LOGS
# ---------------------------
log_group = aws.cloudwatch.LogGroup(
    f"{APP_NAME}-log-group",
    retention_in_days=7
)

# ---------------------------
# NETWORKING
# ---------------------------
default_vpc = aws.ec2.get_vpc(default=True)

subnets = aws.ec2.get_subnets(
    filters=[{
        "name": "vpc-id",
        "values": [default_vpc.id]
    }]
)

alb_sg = aws.ec2.SecurityGroup(
    f"{APP_NAME}-alb-sg",
    vpc_id=default_vpc.id,
    ingress=[
        {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr_blocks": ["0.0.0.0/0"]},
        {"protocol": "tcp", "from_port": 443, "to_port": 443, "cidr_blocks": ["0.0.0.0/0"]},
    ],
    egress=[{
        "protocol": "-1",
        "from_port": 0,
        "to_port": 0,
        "cidr_blocks": ["0.0.0.0/0"]
    }],
)

ecs_sg = aws.ec2.SecurityGroup(
    f"{APP_NAME}-ecs-sg",
    vpc_id=default_vpc.id,
    ingress=[{
        "protocol": "tcp",
        "from_port": CONTAINER_PORT,
        "to_port": CONTAINER_PORT,
        "security_groups": [alb_sg.id]
    }],
    egress=[{
        "protocol": "-1",
        "from_port": 0,
        "to_port": 0,
        "cidr_blocks": ["0.0.0.0/0"]
    }],
)

# ---------------------------
# ALB
# ---------------------------
alb = aws.lb.LoadBalancer(
    f"{APP_NAME}-alb",
    internal=False,
    load_balancer_type="application",
    security_groups=[alb_sg.id],
    subnets=subnets.ids
)

target_group = aws.lb.TargetGroup(
    f"{APP_NAME}-tg",
    port=CONTAINER_PORT,
    protocol="HTTP",
    target_type="ip",
    vpc_id=default_vpc.id,
    health_check={"path": "/"}
)

listener = aws.lb.Listener(
    f"{APP_NAME}-listener",
    load_balancer_arn=alb.arn,
    port=80,
    protocol="HTTP",
    default_actions=[{
        "type": "forward",
        "target_group_arn": target_group.arn
    }]
)

# ---------------------------
# ECS TASK DEFINITION
# ---------------------------
task_definition = aws.ecs.TaskDefinition(
    f"{APP_NAME}-task",
    family=APP_NAME,
    cpu="256",
    memory="512",
    network_mode="awsvpc",
    requires_compatibilities=["FARGATE"],
    execution_role_arn=execution_role.arn,
    task_role_arn=task_role.arn,
    container_definitions=pulumi.Output.all(
        repo.repository_url,
        log_group.name
    ).apply(lambda args: json.dumps([{
        "name": APP_NAME,
        "image": f"{args[0]}:latest",
        "essential": True,
        "portMappings": [{
            "containerPort": CONTAINER_PORT,
            "hostPort": CONTAINER_PORT
        }],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": args[1],
                "awslogs-region": AWS_REGION,
                "awslogs-stream-prefix": "ecs"
            }
        }
    }]))
)

# ---------------------------
# ECS SERVICE
# ---------------------------
service = aws.ecs.Service(
    f"{APP_NAME}-service",
    cluster=cluster.arn,
    task_definition=task_definition.arn,
    desired_count=1,
    launch_type="FARGATE",
    network_configuration={
        "assignPublicIp": True,
        "subnets": subnets.ids,
        "securityGroups": [ecs_sg.id]
    },
    load_balancers=[{
        "targetGroupArn": target_group.arn,
        "containerName": APP_NAME,
        "containerPort": CONTAINER_PORT
    }],
    opts=pulumi.ResourceOptions(depends_on=[listener])
)

# ---------------------------
# OUTPUTS
# ---------------------------
pulumi.export("ecr_url", repo.repository_url)
pulumi.export("cluster_name", cluster.name)
pulumi.export("service_name", service.name)
pulumi.export("alb_url", alb.dns_name)
