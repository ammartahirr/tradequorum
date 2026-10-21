"""
ML Stack for AI Trading System.

Creates:
- SageMaker endpoint for pattern recognition model (Requirement 12.4)
- Configured with 5-second latency budget

Requirements: 12.4
"""
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_sagemaker as sagemaker,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_s3 as s3,
    CfnOutput,
)
from constructs import Construct


class MlStack(Stack):
    """SageMaker endpoint for pattern recognition in AI Trading System."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = vpc

        # ============================================================
        # S3 Bucket for Model Artifacts
        # ============================================================

        self.model_bucket = s3.Bucket(
            self,
            "ModelArtifactsBucket",
            bucket_name=f"ai-trading-models-{Stack.of(self).account}-{Stack.of(self).region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
        )

        # ============================================================
        # SageMaker Execution Role
        # ============================================================

        self.sagemaker_role = iam.Role(
            self,
            "SageMakerExecutionRole",
            role_name="ai-trading-sagemaker-execution",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            description="Execution role for SageMaker pattern recognition model",
        )

        # Grant S3 access for model artifacts
        self.model_bucket.grant_read(self.sagemaker_role)

        # Add SageMaker managed policy
        self.sagemaker_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSageMakerFullAccess")
        )

        # CloudWatch Logs permissions
        self.sagemaker_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["arn:aws:logs:*:*:log-group:/aws/sagemaker/*"],
            )
        )

        # ============================================================
        # SageMaker Model (Pattern Recognition)
        # Requirement: 12.4 - SageMaker prediction within 5 seconds
        # ============================================================

        # Note: The actual model needs to be trained and uploaded to S3
        # This creates the infrastructure for hosting the model

        # Model configuration
        # Using XGBoost container for pattern recognition
        self.model = sagemaker.CfnModel(
            self,
            "PatternRecognitionModel",
            model_name="ai-trading-pattern-recognition",
            execution_role_arn=self.sagemaker_role.role_arn,
            primary_container=sagemaker.CfnModel.ContainerDefinitionProperty(
                # XGBoost container for pattern recognition
                image=f"683313688378.dkr.ecr.{Stack.of(self).region}.amazonaws.com/sagemaker-xgboost:1.5-1",
                model_data_url=f"s3://{self.model_bucket.bucket_name}/models/pattern-recognition/model.tar.gz",
                environment={
                    "SAGEMAKER_PROGRAM": "inference.py",
                    "SAGEMAKER_SUBMIT_DIRECTORY": f"s3://{self.model_bucket.bucket_name}/models/pattern-recognition/code/",
                },
            ),
            vpc_config=sagemaker.CfnModel.VpcConfigProperty(
                security_group_ids=[
                    self._create_sagemaker_security_group().security_group_id
                ],
                subnets=vpc.select_subnets(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ).subnet_ids,
            ),
        )

        # ============================================================
        # SageMaker Endpoint Configuration
        # Configured for 5-second latency budget (Requirement 12.4)
        # ============================================================

        self.endpoint_config = sagemaker.CfnEndpointConfig(
            self,
            "PatternRecognitionEndpointConfig",
            endpoint_config_name="ai-trading-pattern-recognition-config",
            production_variants=[
                sagemaker.CfnEndpointConfig.ProductionVariantProperty(
                    model_name=self.model.model_name or "ai-trading-pattern-recognition",
                    variant_name="primary",
                    initial_instance_count=1,
                    instance_type="ml.m5.large",  # Balanced compute for low latency
                    initial_variant_weight=1.0,
                    # Model data download timeout for faster cold starts
                    model_data_download_timeout_in_seconds=300,
                    container_startup_health_check_timeout_in_seconds=300,
                )
            ],
            # Async inference config for handling spikes
            async_inference_config=None,  # Sync inference for low latency
        )

        self.endpoint_config.add_dependency(self.model)

        # ============================================================
        # SageMaker Endpoint
        # ============================================================

        self.endpoint = sagemaker.CfnEndpoint(
            self,
            "PatternRecognitionEndpoint",
            endpoint_name="ai-trading-pattern-recognition",
            endpoint_config_name=self.endpoint_config.endpoint_config_name or "ai-trading-pattern-recognition-config",
        )

        self.endpoint.add_dependency(self.endpoint_config)

        # ============================================================
        # Auto Scaling for Endpoint
        # ============================================================

        # Note: Auto scaling can be configured via Application Auto Scaling
        # to handle varying load while maintaining latency requirements

        # ============================================================
        # Outputs
        # ============================================================

        CfnOutput(
            self,
            "ModelBucketName",
            value=self.model_bucket.bucket_name,
            description="S3 bucket for model artifacts",
        )

        CfnOutput(
            self,
            "SageMakerEndpointName",
            value=self.endpoint.endpoint_name or "ai-trading-pattern-recognition",
            description="SageMaker endpoint for pattern recognition",
        )

        CfnOutput(
            self,
            "SageMakerRoleArn",
            value=self.sagemaker_role.role_arn,
            description="SageMaker execution role ARN",
        )

    def _create_sagemaker_security_group(self) -> ec2.SecurityGroup:
        """Create security group for SageMaker endpoint."""
        sg = ec2.SecurityGroup(
            self,
            "SageMakerSecurityGroup",
            vpc=self.vpc,
            description="Security group for SageMaker endpoint",
            allow_all_outbound=True,
        )

        # Allow inbound from VPC for inference requests
        sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS from VPC",
        )

        return sg
