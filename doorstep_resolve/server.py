"""
Streamable HTTP MCP Server for Doorstep Resolve.

Provides MCP tools for:
- get_order
- check_replacement_options
- confirm_resolution (idempotent, requires explicit confirmation)
- get_case_history
"""

import json
import uuid
import os
import re
from datetime import datetime
from typing import Optional, Dict, Any, List

from mcp.server.mcpserver import MCPServer
from .config import load_project_env
from .db import Database, DEFAULT_DB_PATH
from .models import Order, Policy
from .resolver import resolve_replacement, evaluate_order_policy

# Ensure .env configuration is loaded automatically at startup
load_project_env()


def create_mcp_server(db: Optional[Database] = None) -> MCPServer:
    """
    Creates and configures the Doorstep Resolve MCP Server with registered tools.
    """
    if db is None:
        db = Database()

    server = MCPServer("doorstep-resolve", version="1.0.0")

    @server.tool(
        name="get_order",
        description="Retrieve order and policy details by order_id from the persistent store.",
    )
    def get_order(order_id: str, current_time: Optional[str] = None) -> Dict[str, Any]:
        if not order_id or not order_id.strip():
            return {
                "status": "ERROR",
                "error": "order_id must be provided and cannot be empty.",
            }

        order_data = db.get_order(order_id.strip())
        if not order_data:
            return {
                "status": "NOT_FOUND",
                "error": f"Order '{order_id}' was not found in the order registry.",
            }

        order_dict = dict(order_data)
        eval_dt = None
        if current_time:
            try:
                eval_dt = datetime.fromisoformat(current_time)
            except Exception:
                eval_dt = None

        delivered_at_dt = datetime.fromisoformat(order_dict["delivered_at"])
        w_days = int(order_dict.get("return_window_days", 30))
        rep_allowed = bool(order_dict.get("replacement_allowed", 1))

        policy_eval = evaluate_order_policy(
            delivered_at=delivered_at_dt,
            return_window_days=w_days,
            replacement_allowed=rep_allowed,
            current_time=eval_dt,
        )
        order_dict["policy"] = policy_eval

        return {
            "status": "SUCCESS",
            "order": order_dict,
        }

    @server.tool(
        name="check_replacement_options",
        description=(
            "Evaluate replacement eligibility, warehouse inventory, transit durations, "
            "and cutoffs against customer deadline to return ranked resolution options with evidence."
        ),
    )
    def check_replacement_options(
        order_id: str,
        customer_deadline: str,
        current_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not order_id or not order_id.strip():
            return {"status": "ERROR", "error": "order_id is required."}

        order_data = db.get_order(order_id.strip())
        if not order_data:
            return {
                "status": "NOT_FOUND",
                "error": f"Order '{order_id}' was not found.",
            }

        # Parse customer deadline
        try:
            deadline_dt = datetime.fromisoformat(customer_deadline)
        except (ValueError, TypeError) as exc:
            return {
                "status": "INVALID_INPUT",
                "error": f"Invalid ISO format for customer_deadline: '{customer_deadline}'. Details: {exc}",
            }

        # Parse or default current_time
        if current_time:
            try:
                current_dt = datetime.fromisoformat(current_time)
            except (ValueError, TypeError) as exc:
                return {
                    "status": "INVALID_INPUT",
                    "error": f"Invalid ISO format for current_time: '{current_time}'. Details: {exc}",
                }
        else:
            # Check if order_id belongs to a known scenario with default_current_time
            # to preserve deterministic scenario simulation and prevent host-clock contamination
            sim_time = None
            for sc in SCENARIOS_METADATA:
                if sc.get("order_id") == order_id.strip():
                    sim_time = sc.get("default_current_time")
                    break
            if sim_time:
                try:
                    current_dt = datetime.fromisoformat(sim_time)
                except Exception:
                    current_dt = datetime.now()
            else:
                # Match timezone awareness of deadline_dt if none provided
                if deadline_dt.tzinfo is not None:
                    current_dt = datetime.now(deadline_dt.tzinfo)
                else:
                    current_dt = datetime.now()

        # Parse delivery time from order
        delivered_at_dt = datetime.fromisoformat(order_data["delivered_at"])

        # Align timezone awareness if needed
        if deadline_dt.tzinfo is not None and delivered_at_dt.tzinfo is None:
            delivered_at_dt = delivered_at_dt.replace(tzinfo=deadline_dt.tzinfo)
        elif deadline_dt.tzinfo is None and delivered_at_dt.tzinfo is not None:
            delivered_at_dt = delivered_at_dt.replace(tzinfo=None)

        order_obj = Order(
            order_id=order_data["order_id"],
            item_id=order_data["item_id"],
            item_name=order_data["item_name"],
            price=order_data["price"],
            delivered_at=delivered_at_dt,
        )
        policy_obj = Policy(
            return_window_days=order_data.get("return_window_days", 30),
            replacement_allowed=bool(order_data.get("replacement_allowed", 1)),
        )

        inventory = db.get_inventory_for_item(order_obj.item_id)
        shipping_estimates = db.get_shipping_estimates()

        try:
            options = resolve_replacement(
                order=order_obj,
                policy=policy_obj,
                inventory=inventory,
                shipping_estimates=shipping_estimates,
                customer_deadline=deadline_dt,
                current_time=current_dt,
            )
        except Exception as exc:
            return {
                "status": "RESOLVER_ERROR",
                "error": str(exc),
            }

        case_id = f"CASE-{order_id}-{uuid.uuid4().hex[:6].upper()}"

        # Record check event to case history
        db.add_case_history_event(
            case_id=case_id,
            order_id=order_id,
            event_type="OPTIONS_CHECKED",
            details={
                "customer_deadline": customer_deadline,
                "current_time": current_dt.isoformat(),
                "options_count": len(options),
                "meets_any_option": any(o.eligible and o.meets_deadline for o in options),
            },
        )

        options_dict_list = [o.to_dict() for o in options]
        policy_eval = evaluate_order_policy(
            delivered_at=delivered_at_dt,
            return_window_days=policy_obj.return_window_days,
            replacement_allowed=policy_obj.replacement_allowed,
            current_time=current_dt,
        )
        return {
            "status": "SUCCESS",
            "case_id": case_id,
            "order_id": order_id,
            "item_name": order_data["item_name"],
            "customer_deadline": deadline_dt.isoformat(),
            "evaluated_at": current_dt.isoformat(),
            "options_count": len(options),
            "meets_any_option": any(o.eligible and o.meets_deadline for o in options),
            "top_option": options_dict_list[0] if options_dict_list else None,
            "options": options_dict_list,
            "policy_evaluation": policy_eval,
        }

    @server.tool(
        name="confirm_resolution",
        description=(
            "Idempotently record and execute a chosen resolution option after explicit customer confirmation. "
            "Requires customer_agreed=True and a unique idempotency_key."
        ),
    )
    def confirm_resolution(
        order_id: str,
        option_id: str,
        customer_agreed: bool,
        idempotency_key: str,
        case_id: Optional[str] = None,
        customer_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not idempotency_key or not idempotency_key.strip():
            return {
                "status": "ERROR",
                "error": "idempotency_key is required to confirm a resolution.",
            }

        cleaned_idempotency_key = idempotency_key.strip()

        # Reject cross-order token prefix if key is order-prefixed (e.g. IDEM-ORD-1001-...)
        token_order_match = re.match(r"^IDEM-(ORD-\d+)-", cleaned_idempotency_key)
        if token_order_match and token_order_match.group(1) != order_id:
            return {
                "status": "ERROR",
                "error": (
                    f"Idempotency token '{cleaned_idempotency_key}' belongs to order "
                    f"'{token_order_match.group(1)}' and cannot be used for order '{order_id}'."
                ),
            }

        # Check for duplicate submission (Idempotency Guard)
        existing_res = db.get_resolution_by_idempotency_key(cleaned_idempotency_key)
        if existing_res:
            if existing_res["order_id"] != order_id:
                return {
                    "status": "ERROR",
                    "error": (
                        f"Idempotency token '{cleaned_idempotency_key}' is already associated with order "
                        f"'{existing_res['order_id']}' and cannot be reused for order '{order_id}'."
                    ),
                }
            db.add_case_history_event(
                case_id=existing_res["case_id"],
                order_id=existing_res["order_id"],
                event_type="IDEMPOTENT_RETRY_DETECTED",
                details={
                    "idempotency_key": cleaned_idempotency_key,
                    "option_id": option_id,
                },
            )
            return {
                "status": "ALREADY_CONFIRMED",
                "idempotent_replay": True,
                "message": "Resolution was already recorded with this idempotency_key. Duplicate action prevented.",
                "resolution": existing_res,
            }

        # Explicit Customer Agreement Requirement
        if not customer_agreed:
            assigned_case_id = case_id if case_id else f"CASE-{order_id}-{uuid.uuid4().hex[:6].upper()}"
            db.add_case_history_event(
                case_id=assigned_case_id,
                order_id=order_id,
                event_type="CONFIRMATION_REJECTED",
                details={
                    "option_id": option_id,
                    "idempotency_key": cleaned_idempotency_key,
                    "reason": "Resolution requires explicit customer agreement before recording (customer_agreed must be True).",
                    "customer_notes": customer_notes,
                },
            )
            return {
                "status": "CONFIRMATION_REQUIRED",
                "error": "Resolution requires explicit customer agreement before recording (customer_agreed must be True).",
                "order_id": order_id,
                "option_id": option_id,
                "case_id": assigned_case_id,
            }

        order_data = db.get_order(order_id)
        if not order_data:
            return {
                "status": "NOT_FOUND",
                "error": f"Order '{order_id}' not found.",
            }

        # Validate that option_id corresponds to a valid warehouse route for this order's item
        if option_id.startswith("REPLACE_"):
            parts = option_id.split("_")
            if len(parts) >= 2:
                wh_id = parts[1]
                matching_inv = [
                    inv for inv in db.get_inventory_for_item(order_data["item_id"])
                    if inv.warehouse_id == wh_id and inv.quantity > 0
                ]
                if not matching_inv:
                    return {
                        "status": "ERROR",
                        "error": f"Option '{option_id}' does not correspond to a valid fulfillment warehouse with stock for order '{order_id}'.",
                    }

        assigned_case_id = case_id if case_id else f"CASE-{order_id}-{uuid.uuid4().hex[:6].upper()}"
        confirmed_at = datetime.now().isoformat()

        # Simulated fulfillment action
        action_type = "SIMULATED_REPLACEMENT_DISPATCH" if "REPLACE" in option_id else "SIMULATED_ALTERNATIVE_ACTION"
        simulated_evidence = [
            f"Customer explicitly confirmed resolution option '{option_id}'.",
            f"Idempotency token '{cleaned_idempotency_key}' validated and locked.",
            f"Simulated dispatch action '{action_type}' recorded without external side effects.",
        ]

        recorded = db.record_resolution(
            case_id=assigned_case_id,
            order_id=order_id,
            idempotency_key=cleaned_idempotency_key,
            action_type=action_type,
            option_id=option_id,
            status="CONFIRMED_SIMULATED",
            confirmed_at=confirmed_at,
            estimated_arrival=None,
            evidence=simulated_evidence,
            customer_notes=customer_notes,
        )

        return {
            "status": "CONFIRMED",
            "idempotent_replay": False,
            "resolution": recorded,
            "simulated_fulfillment": {
                "status": "QUEUED",
                "simulated_tracking_id": f"SIM-TRK-{uuid.uuid4().hex[:8].upper()}",
                "notice": "Simulated resolution recorded. No external orders or financial transactions were executed.",
            },
        }

    @server.tool(
        name="get_case_history",
        description="Retrieve the persistent audit event history for an order or case from SQLite.",
    )
    def get_case_history(
        order_id: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        events = db.get_case_history(order_id=order_id, case_id=case_id)
        return {
            "status": "SUCCESS",
            "order_id": order_id,
            "case_id": case_id,
            "event_count": len(events),
            "events": events,
        }

    # Also attach functions directly for convenient direct programmatic calls
    server.get_order = get_order
    server.check_replacement_options = check_replacement_options
    server.confirm_resolution = confirm_resolution
    server.get_case_history = get_case_history

    return server



from starlette.responses import JSONResponse, FileResponse
from starlette.requests import Request
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from pathlib import Path


SCENARIOS_METADATA = [
    {
        "id": "scenario_1",
        "order_id": "ORD-1001",
        "title": "Scenario 1: Meets Deadline (Proven Feasible)",
        "badge": "Feasible",
        "badge_color": "emerald",
        "description": "Standard ground from East warehouse arrives before Friday 6 PM deadline.",
        "default_deadline": "2026-10-22T18:00:00",
        "default_current_time": "2026-10-20T10:00:00",
    },
    {
        "id": "scenario_2",
        "order_id": "ORD-1002",
        "title": "Scenario 2: Arrives Too Late (Misses Deadline)",
        "badge": "Misses Deadline",
        "badge_color": "amber",
        "description": "Cutoff passed + 3-day transit misses strict Thursday noon deadline.",
        "default_deadline": "2026-10-22T12:00:00",
        "default_current_time": "2026-10-20T15:30:00",
    },
    {
        "id": "scenario_3",
        "order_id": "ORD-1003",
        "title": "Scenario 3: Stock Unavailable (Out of Stock)",
        "badge": "Out of Stock",
        "badge_color": "rose",
        "description": "Zero stock across regional warehouses. Resolver flags immediately.",
        "default_deadline": "2026-10-25T18:00:00",
        "default_current_time": "2026-10-20T11:00:00",
    },
    {
        "id": "scenario_4",
        "order_id": "ORD-1004",
        "title": "Scenario 4: Return Window Expired",
        "badge": "Policy Expired",
        "badge_color": "rose",
        "description": "Order delivered 45 days ago; 30-day replacement window exceeded.",
        "default_deadline": "2026-10-25T18:00:00",
        "default_current_time": "2026-10-20T11:00:00",
    },
    {
        "id": "scenario_5",
        "order_id": "ORD-1005",
        "title": "Scenario 5: Expedited Rescue (Air Beats Ground)",
        "badge": "Expedited Rescue",
        "badge_color": "blue",
        "description": "Standard ground misses deadline, but Overnight Air arrives on time.",
        "default_deadline": "2026-10-22T12:00:00",
        "default_current_time": "2026-10-20T16:00:00",
    },
]


def create_app(
    db: Optional[Database] = None,
    enable_dns_rebinding_protection: bool = False,
    mcp_server_url: Optional[str] = None,
    orchestrator: Optional[Any] = None,
):
    """
    Returns the Starlette ASGI application serving both:
    1. Streamable HTTP MCP endpoint at /mcp
    2. Conversational REST API at /api/*
    3. Agent Orchestrator endpoint at /api/agent/resolve
    4. Static frontend assets at /
    """
    from mcp.server.transport_security import TransportSecuritySettings

    if db is None:
        db = Database()

    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=enable_dns_rebinding_protection,
        allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
    )
    server = create_mcp_server(db=db)
    asgi_app = server.streamable_http_app(transport_security=security_settings)

    # Add REST API routes for Frontend & Integration testing
    def _get_active_provider_info():
        try:
            from .agent import get_default_provider
            p = get_default_provider()
            return p.provider_name, p.is_mock
        except Exception:
            return "deterministic-mock-test-provider", True

    async def api_provider(request: Request):
        p_name, is_m = _get_active_provider_info()
        return JSONResponse({
            "status": "SUCCESS",
            "provider_name": p_name,
            "is_mock": is_m,
        })

    async def api_scenarios(request: Request):
        p_name, is_m = _get_active_provider_info()
        return JSONResponse({
            "status": "SUCCESS",
            "scenarios": SCENARIOS_METADATA,
            "provider_name": p_name,
            "is_mock": is_m,
        })

    async def api_get_order(request: Request):
        order_id = request.path_params.get("order_id", "")
        current_time = request.query_params.get("current_time")
        res = server.get_order(order_id, current_time=current_time)
        status_code = 200 if res.get("status") == "SUCCESS" else (404 if res.get("status") == "NOT_FOUND" else 400)
        return JSONResponse(res, status_code=status_code)

    async def api_check_options(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"status": "ERROR", "error": "Invalid JSON body"}, status_code=400)

        res = server.check_replacement_options(
            order_id=body.get("order_id", ""),
            customer_deadline=body.get("customer_deadline", ""),
            current_time=body.get("current_time"),
        )
        status_code = 200 if res.get("status") == "SUCCESS" else 400
        return JSONResponse(res, status_code=status_code)

    async def api_confirm(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"status": "ERROR", "error": "Invalid JSON body"}, status_code=400)

        res = server.confirm_resolution(
            order_id=body.get("order_id", ""),
            option_id=body.get("option_id", ""),
            customer_agreed=body.get("customer_agreed", False),
            idempotency_key=body.get("idempotency_key", ""),
            customer_notes=body.get("customer_notes"),
            case_id=body.get("case_id"),
        )
        status_code = 200 if res.get("status") in ("CONFIRMED", "ALREADY_CONFIRMED") else 400
        return JSONResponse(res, status_code=status_code)

    async def api_history(request: Request):
        order_id = request.path_params.get("order_id")
        res = server.get_case_history(order_id=order_id)
        return JSONResponse(res)

    async def api_tool_call(request: Request):
        """Unified MCP tool runner for visible activity trace."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"status": "ERROR", "error": "Invalid JSON body"}, status_code=400)

        tool_name = body.get("tool")
        args = body.get("arguments", {})

        if tool_name == "get_order":
            res = server.get_order(args.get("order_id", ""), current_time=args.get("current_time"))
        elif tool_name == "check_replacement_options":
            res = server.check_replacement_options(
                order_id=args.get("order_id", ""),
                customer_deadline=args.get("customer_deadline", ""),
                current_time=args.get("current_time"),
            )
        elif tool_name == "confirm_resolution":
            res = server.confirm_resolution(
                order_id=args.get("order_id", ""),
                option_id=args.get("option_id", ""),
                customer_agreed=args.get("customer_agreed", False),
                idempotency_key=args.get("idempotency_key", ""),
                customer_notes=args.get("customer_notes"),
                case_id=args.get("case_id"),
            )
        elif tool_name == "get_case_history":
            res = server.get_case_history(
                order_id=args.get("order_id"),
                case_id=args.get("case_id"),
            )
        else:
            return JSONResponse({"status": "ERROR", "error": f"Unknown tool: '{tool_name}'"}, status_code=404)

        return JSONResponse(res)

    async def api_agent_resolve(request: Request):
        """
        Conversational agent endpoint using DoorstepAgentOrchestrator over real MCP tools.
        Enforces read-only tools and never invokes confirm_resolution.
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"status": "ERROR", "error": "Invalid JSON body", "is_success": False},
                status_code=400,
            )

        query = (body.get("query") or "").strip()
        order_id = (body.get("order_id") or "").strip()
        customer_deadline = body.get("customer_deadline")
        current_time = body.get("current_time")

        # Synchronize order_id if query explicitly mentions an order
        import re
        query_order_match = re.search(r"ORD-\d+", query)
        if query_order_match:
            queried_order = query_order_match.group(0)
            if not order_id or order_id != queried_order:
                order_id = queried_order
                # If deadline not explicitly formatted in query, reset to queried order's scenario default
                if not re.search(r"\d{4}-\d{2}-\d{2}", query):
                    customer_deadline = None
                if not current_time or current_time in ("2026-10-20T10:00:00", "2026-10-20T16:00:00", "2026-10-20T11:00:00", "2026-10-20T15:30:00"):
                    current_time = None

        if not query and not order_id:
            return JSONResponse(
                {
                    "status": "ERROR",
                    "error": "Either 'query' or 'order_id' is required to resolve delivery options.",
                    "is_success": False,
                },
                status_code=400,
            )

        if not query and order_id:
            query = f"Check replacement options for {order_id}"
            if customer_deadline:
                query += f" with deadline {customer_deadline}"

        context = {}
        if order_id:
            context["order_id"] = order_id
        if not customer_deadline and order_id:
            for sc in SCENARIOS_METADATA:
                if sc.get("order_id") == order_id:
                    customer_deadline = sc.get("default_deadline")
                    break
        if customer_deadline:
            context["customer_deadline"] = customer_deadline
        if not current_time and order_id:
            for sc in SCENARIOS_METADATA:
                if sc.get("order_id") == order_id:
                    current_time = sc.get("default_current_time")
                    break
        if current_time:
            context["current_time"] = current_time

        try:
            active_orchestrator = orchestrator
            if active_orchestrator is None:
                from .agent import DoorstepAgentOrchestrator, DEFAULT_MCP_SERVER_URL
                active_server_url = mcp_server_url or os.getenv("DOORSTEP_MCP_SERVER_URL", DEFAULT_MCP_SERVER_URL)
                active_orchestrator = DoorstepAgentOrchestrator(server_url=active_server_url)

            result = await active_orchestrator.run(query=query, context=context)
            res_dict = result.to_dict()
            res_dict["status"] = "SUCCESS" if result.is_success else "ERROR"
            status_code = 200 if result.is_success else 400
            return JSONResponse(res_dict, status_code=status_code)
        except Exception as exc:
            p_name, is_m = _get_active_provider_info()
            return JSONResponse(
                {
                    "status": "ERROR",
                    "error": f"Agent orchestration error: {str(exc)}",
                    "is_success": False,
                    "provider_name": p_name,
                    "is_mock": is_m,
                },
                status_code=400,
            )

    asgi_app.add_route("/api/provider", api_provider, methods=["GET"])
    asgi_app.add_route("/api/scenarios", api_scenarios, methods=["GET"])
    asgi_app.add_route("/api/orders/{order_id}", api_get_order, methods=["GET"])
    asgi_app.add_route("/api/check-options", api_check_options, methods=["POST"])
    asgi_app.add_route("/api/confirm", api_confirm, methods=["POST"])
    asgi_app.add_route("/api/history/{order_id}", api_history, methods=["GET"])
    asgi_app.add_route("/api/mcp/tool-call", api_tool_call, methods=["POST"])
    asgi_app.add_route("/api/agent/resolve", api_agent_resolve, methods=["POST"])

    # Serve static frontend files if built
    dist_path = Path(__file__).parent.parent / "frontend" / "dist"
    if dist_path.exists() and (dist_path / "index.html").exists():
        asgi_app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")

    # Add CORS middleware
    asgi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return asgi_app


# Module-level ASGI app for uvicorn
app = create_app()

if __name__ == "__main__":
    import uvicorn
    print("Starting Doorstep Resolve Streamable HTTP MCP server on http://127.0.0.1:8000/mcp ...")
    uvicorn.run(app, host="127.0.0.1", port=8000)

