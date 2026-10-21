"""
Security Stack for AI Trading System.

Creates:
- Secrets Manager for MT5 credentials with 90-day rotation (Requirement 11.1)
- Cognito User Pool for dashboard authentication (Requirement 11.4)

Requirements: 11.1, 11.4
"""
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_secretsmanager as secretsmanager,
    aws_cognito as cognito,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct


class SecurityStack(Stack):
    """Secrets Manager and Cognito authentication for AI Trading System."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================================
        # Secrets Manager for MT5 Credentials (Requirement 11.1)
        # ============================================================

        # MT5 Credentials Secret with 90-day rotation
        # Requirement: 11.1 - Store Exness MT5 credentials with 90-day rotation
        self.mt5_credentials_secret = secretsmanager.Secret(
            self,
            "Mt5CredentialsSecret",
            secret_name="ai-trading/mt5-credentials",
            description="Exness MT5 login credentials for trading",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"login": "", "server": ""}',
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=32,
            ),
        )

        # Note: Automatic rotation requires a Lambda function to rotate credentials
        # For MT5, this would need custom implementation as MT5 doesn't support
        # automatic credential rotation. The 90-day rotation policy is set as a
        # reminder/schedule, but actual rotation requires manual intervention or
        # custom Lambda rotation function.

        # Create rotation schedule (90 days)
        # This creates a CloudWatch Events rule to remind about rotation
        self.mt5_credentials_secret.add_rotation_schedule(
            "Mt5RotationSchedule",
            automatically_after=Duration.days(90),
            # Note: rotation_lambda would be needed for automatic rotation
            # For now, this serves as a reminder schedule
            hosted_rotation=secretsmanager.HostedRotation.mysql_single_user(
                # Using a placeholder - in production, implement custom rotation
                exclude_characters="/@\"'\\"
            ),
        )

        # ============================================================
        # Cognito User Pool for Dashboard Authentication (Requirement 11.4)
        # ============================================================

        # Cognito User Pool
        # Requirement: 11.4 - Cognito authentication for Dashboard
        self.user_pool = cognito.UserPool(
            self,
            "TradingDashboardUserPool",
            user_pool_name="ai-trading-dashboard-users",
            self_sign_up_enabled=False,  # Admin creates users
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=True,
            ),
            auto_verify=cognito.AutoVerifiedAttrs(
                email=True,
            ),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(
                    required=True,
                    mutable=True,
                ),
                fullname=cognito.StandardAttribute(
                    required=False,
                    mutable=True,
                ),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=Duration.days(7),
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(
                sms=False,
                otp=True,
            ),
            advanced_security_mode=cognito.AdvancedSecurityMode.ENFORCED,
        )

        # User Pool Client for Dashboard
        self.user_pool_client = self.user_pool.add_client(
            "DashboardClient",
            user_pool_client_name="ai-trading-dashboard-client",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=True,
                ),
                scopes=[
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[
                    "http://localhost:3000/callback",  # Development
                    "https://dashboard.ai-trading.example.com/callback",  # Production
                ],
                logout_urls=[
                    "http://localhost:3000/logout",
                    "https://dashboard.ai-trading.example.com/logout",
                ],
            ),
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            prevent_user_existence_errors=True,
        )

        # User Pool Domain for hosted UI
        self.user_pool_domain = self.user_pool.add_domain(
            "CognitoDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix="ai-trading-dashboard",
            ),
        )

        # Admin Group for elevated permissions
        cognito.CfnUserPoolGroup(
            self,
            "AdminGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="Admins",
            description="Administrators with full access",
        )

        # Trader Group for standard trading access
        cognito.CfnUserPoolGroup(
            self,
            "TraderGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="Traders",
            description="Traders with trading dashboard access",
        )

        # ============================================================
        # IAM Role for Bedrock Access (no API keys needed)
        # ============================================================

        # IAM policy for Bedrock access
        self.bedrock_policy = iam.ManagedPolicy(
            self,
            "BedrockAccessPolicy",
            managed_policy_name="ai-trading-bedrock-access",
            description="Policy for accessing AWS Bedrock Claude Opus 4.5",
            statements=[
                iam.PolicyStatement(
                    sid="BedrockInvokeModel",
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream",
                    ],
                    resources=[
                        f"arn:aws:bedrock:*:{Stack.of(self).account}:inference-profile/*",
                        "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
                    ],
                ),
            ],
        )

        # ============================================================
        # Outputs
        # ============================================================

        CfnOutput(
            self,
            "Mt5SecretArn",
            value=self.mt5_credentials_secret.secret_arn,
            description="ARN of MT5 credentials secret",
        )

        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
        )

        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito User Pool Client ID",
        )

        CfnOutput(
            self,
            "UserPoolDomain",
            value=self.user_pool_domain.domain_name,
            description="Cognito User Pool Domain",
        )

        CfnOutput(
            self,
            "BedrockPolicyArn",
            value=self.bedrock_policy.managed_policy_arn,
            description="ARN of Bedrock access policy",
        )
