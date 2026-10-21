"""
API Stack for AI Trading System.

Creates:
- WebSocket API for real-time dashboard updates (Requirement 12.5)
- Support for 500 concurrent connections
- Rate limiting on API endpoints (Requirement 11.7)
- Cognito authentication protection (Requirement 11.4)

Requirements: 11.4, 11.7, 12.5
"""
from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_apigatewayv2_authorizers as authorizers,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compute_stack import ComputeStack
    from .security_stack import SecurityStack


class ApiStack(Stack):
    """API Gateway WebSocket API for AI Trading System."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        compute_stack: "ComputeStack",
        security_stack: "SecurityStack",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.compute_stack = compute_stack
        self.security_stack = security_stack

        # ============================================================
        # WebSocket API (Requirement 12.5)
        # Supports up to 500 concurrent connections
        # ============================================================

        self.websocket_api = apigwv2.WebSocketApi(
            self,
            "TradingWebSocketApi",
            api_name="ai-trading-websocket",
            description="WebSocket API for real-time trading dashboard updates",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    "ConnectIntegration",
                    compute_stack.websocket_connect_function,
                ),
            ),
            disconnect_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    "DisconnectIntegration",
                    compute_stack.websocket_disconnect_function,
                ),
            ),
            default_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    "DefaultIntegration",
                    compute_stack.websocket_message_function,
                ),
            ),
        )

        # WebSocket Stage with throttling
        # Requirement: 11.7 - Rate limiting on API endpoints
        # Requirement: 12.5 - Support 500 concurrent connections
        self.websocket_stage = apigwv2.WebSocketStage(
            self,
            "WebSocketProdStage",
            web_socket_api=self.websocket_api,
            stage_name="prod",
            auto_deploy=True,
            throttle=apigwv2.ThrottleSettings(
                rate_limit=1000,  # Requests per second
                burst_limit=500,  # Concurrent connections (Requirement 12.5)
            ),
        )

        # Grant Lambda permission to manage WebSocket connections
        self.websocket_api.grant_manage_connections(compute_stack.websocket_message_function)
        self.websocket_api.grant_manage_connections(compute_stack.position_manager_function)
        self.websocket_api.grant_manage_connections(compute_stack.order_executor_function)

        # Add WebSocket endpoint to Lambda environment
        compute_stack.position_manager_function.add_environment(
            "WEBSOCKET_ENDPOINT",
            f"{self.websocket_api.api_endpoint}/{self.websocket_stage.stage_name}",
        )
        compute_stack.order_executor_function.add_environment(
            "WEBSOCKET_ENDPOINT",
            f"{self.websocket_api.api_endpoint}/{self.websocket_stage.stage_name}",
        )

        # ============================================================
        # HTTP API for REST endpoints (with Cognito auth)
        # Requirement: 11.4 - Cognito authentication for Dashboard
        # ============================================================

        # Cognito JWT Authorizer
        self.cognito_authorizer = authorizers.HttpJwtAuthorizer(
            "CognitoAuthorizer",
            jwt_issuer=f"https://cognito-idp.{Stack.of(self).region}.amazonaws.com/{security_stack.user_pool.user_pool_id}",
            jwt_audience=[security_stack.user_pool_client.user_pool_client_id],
        )

        # HTTP API for dashboard REST endpoints
        self.http_api = apigwv2.HttpApi(
            self,
            "TradingHttpApi",
            api_name="ai-trading-http",
            description="HTTP API for trading dashboard",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["http://localhost:3000", "https://dashboard.ai-trading.example.com"],
                allow_methods=[apigwv2.CorsHttpMethod.GET, apigwv2.CorsHttpMethod.POST],
                allow_headers=["Authorization", "Content-Type"],
                max_age=Duration.hours(1),
            ),
            default_authorizer=self.cognito_authorizer,
        )

        # HTTP API Stage with throttling
        # Requirement: 11.7 - Rate limiting
        http_stage = apigwv2.HttpStage(
            self,
            "HttpProdStage",
            http_api=self.http_api,
            stage_name="prod",
            auto_deploy=True,
            throttle=apigwv2.ThrottleSettings(
                rate_limit=100,  # Requests per second
                burst_limit=200,
            ),
        )

        # ============================================================
        # Outputs
        # ============================================================

        CfnOutput(
            self,
            "WebSocketApiEndpoint",
            value=f"{self.websocket_api.api_endpoint}/{self.websocket_stage.stage_name}",
            description="WebSocket API endpoint for real-time updates",
        )

        CfnOutput(
            self,
            "WebSocketApiId",
            value=self.websocket_api.api_id,
            description="WebSocket API ID",
        )

        CfnOutput(
            self,
            "HttpApiEndpoint",
            value=self.http_api.api_endpoint or "",
            description="HTTP API endpoint for REST calls",
        )
