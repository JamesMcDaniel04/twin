"""Release management workflow template."""

RELEASE_WORKFLOW_TEMPLATE = {
    "name": "release_management",
    "steps": [
        "create_release_plan",
        "run_regression_tests",
        "announce_change",
        "deploy_to_production",
        "collect_metrics",
    ],
}
