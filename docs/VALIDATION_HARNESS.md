# Validation Harness & QA Dashboard Documentation

## Overview

The Validation Harness is a comprehensive testing framework for measuring the precision, recall, and ranking quality of the TwinOps knowledge retrieval system. It provides automated testing, metrics computation, and a QA dashboard for monitoring retrieval performance over time.

## Architecture

```
┌──────────────────┐
│  Test Cases      │
│  (JSON File)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────┐
│  ValidationHarness       │
│  - Load Test Cases       │
│  - Run Queries           │
│  - Compute Metrics       │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────────────┐
│  OrchestrationRouter     │
│  (Query Execution)       │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────────────┐
│  MongoDB                 │
│  (Results Storage)       │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────────────┐
│  QA Dashboard API        │
│  /api/v1/validation/*    │
└──────────────────────────┘
```

## Metrics

The harness computes the following metrics:

### 1. Precision

**Formula**: `True Positives / (True Positives + False Positives)`

Measures the fraction of retrieved documents that are relevant.

### 2. Recall

**Formula**: `True Positives / (True Positives + False Negatives)`

Measures the fraction of relevant documents that were retrieved.

### 3. F1 Score

**Formula**: `2 * (Precision * Recall) / (Precision + Recall)`

Harmonic mean of precision and recall.

### 4. NDCG (Normalized Discounted Cumulative Gain)

Measures ranking quality by considering the position of relevant documents.

**Formula**:
```
DCG@k = Σ (relevance_i / log2(rank_i + 1))
NDCG@k = DCG@k / IDCG@k
```

Higher NDCG indicates better ranking.

### 5. MRR (Mean Reciprocal Rank)

**Formula**: `1 / rank_of_first_relevant_document`

Measures how quickly the first relevant result appears.

### 6. MAP (Mean Average Precision)

Average of precision values at each relevant document position.

**Formula**: `Σ (Precision@k * relevance_k) / total_relevant`

---

## Test Case Format

Test cases are defined in JSON format:

```json
{
  "test_cases": [
    {
      "test_id": "unique-test-id",
      "query": "Test query string",
      "expected_documents": ["doc-id-1", "doc-id-2"],
      "relevance_scores": {
        "doc-id-1": 1.0,
        "doc-id-2": 0.8
      },
      "category": "container|incident|runbook|...",
      "description": "Test description"
    }
  ]
}
```

### Fields

- **test_id**: Unique identifier for the test case
- **query**: Query string to test
- **expected_documents**: List of document IDs expected to be relevant
- **relevance_scores**: Optional graded relevance (0.0 to 1.0)
  - If omitted, binary relevance (0 or 1) is assumed
- **category**: Test category for grouping
- **description**: Human-readable description

---

## API Endpoints

### 1. Run Validation

**POST** `/api/v1/validation/run`

Execute a validation run with all test cases.

#### Request Body

```json
{
  "test_suite_name": "optional-suite-name",
  "test_case_ids": ["test-1", "test-2"]  // Optional: run specific tests
}
```

#### Response (202 Accepted)

```json
{
  "run_id": "uuid",
  "status": "completed",
  "test_count": 10,
  "executed_count": 10,
  "timestamp": "2024-01-15T10:30:00Z",
  "aggregate_metrics": {
    "mean_precision": 0.85,
    "mean_recall": 0.78,
    "mean_f1": 0.81,
    "mean_ndcg": 0.89,
    "mean_mrr": 0.92,
    "mean_map": 0.87
  }
}
```

### 2. Upload Test Cases

**POST** `/api/v1/validation/test-cases/upload`

Upload a JSON file with test cases.

#### Request

- **Form Data**: `file` (multipart/form-data)

#### Response (201 Created)

```json
{
  "message": "Uploaded 10 test cases",
  "test_count": 10,
  "filename": "test_cases.json"
}
```

### 3. List Validation Runs

**GET** `/api/v1/validation/runs?limit=50&offset=0`

List historical validation runs.

#### Response

```json
[
  {
    "run_id": "uuid",
    "timestamp": "2024-01-15T10:30:00Z",
    "test_count": 10,
    "executed_count": 10,
    "aggregate_metrics": {...},
    "metrics": [...],
    "results": [...]
  }
]
```

### 4. Get Validation Run Details

**GET** `/api/v1/validation/runs/{run_id}`

Get detailed results for a specific run.

#### Response

```json
{
  "run_id": "uuid",
  "timestamp": "2024-01-15T10:30:00Z",
  "test_count": 10,
  "executed_count": 10,
  "aggregate_metrics": {
    "mean_precision": 0.85,
    "mean_recall": 0.78,
    "mean_f1": 0.81,
    "mean_ndcg": 0.89,
    "mean_mrr": 0.92,
    "mean_map": 0.87,
    "total_retrieved": 150,
    "total_relevant": 100,
    "total_true_positives": 85,
    "total_false_positives": 65,
    "total_false_negatives": 15
  },
  "metrics": [
    {
      "test_id": "test-1",
      "precision": 0.9,
      "recall": 0.8,
      "f1_score": 0.85,
      "ndcg": 0.92,
      "mrr": 1.0,
      "map_score": 0.88,
      "retrieved_count": 15,
      "relevant_count": 10
    }
  ],
  "results": [
    {
      "test_id": "test-1",
      "query": "Test query",
      "retrieved_documents": ["doc-1", "doc-2", ...],
      "execution_time_ms": 234.5
    }
  ]
}
```

### 5. Get Dashboard Summary

**GET** `/api/v1/validation/dashboard`

Get summary statistics for the QA dashboard.

#### Response

```json
{
  "total_runs": 25,
  "latest_run": {...},
  "mean_precision": 0.85,
  "mean_recall": 0.78,
  "mean_f1": 0.81,
  "mean_ndcg": 0.89,
  "trend": {
    "precision": [0.82, 0.84, 0.85, 0.86, ...],
    "recall": [0.75, 0.76, 0.78, 0.79, ...],
    "f1": [0.78, 0.80, 0.81, 0.82, ...],
    "ndcg": [0.87, 0.88, 0.89, 0.90, ...]
  }
}
```

### 6. Delete Validation Run

**DELETE** `/api/v1/validation/runs/{run_id}`

Delete a validation run.

#### Response (204 No Content)

---

## Usage Examples

### Programmatic Usage

```python
from backend.validation.harness import ValidationHarness, TestCase

# Initialize harness
harness = ValidationHarness()

# Add test case programmatically
test_case = TestCase(
    test_id="test-1",
    query="What containers have critical vulnerabilities?",
    expected_documents=["doc-1", "doc-2"],
    relevance_scores={"doc-1": 1.0, "doc-2": 0.8},
    category="container"
)
harness.add_test_case(test_case)

# Or load from file
harness.load_test_cases_from_file("backend/validation/test_cases.json")

# Run all tests
results = await harness.run_all_tests()

# Save results
await harness.save_results(results, "validation_results.json")
```

### CLI Usage

```bash
# Run validation via API
curl -X POST http://localhost:8000/api/v1/validation/run

# Upload test cases
curl -X POST http://localhost:8000/api/v1/validation/test-cases/upload \
  -F "file=@test_cases.json"

# Get dashboard summary
curl http://localhost:8000/api/v1/validation/dashboard
```

### Python Script

```python
import asyncio
from backend.validation.harness import ValidationHarness

async def main():
    harness = ValidationHarness()
    harness.load_test_cases_from_file("backend/validation/test_cases.json")

    results = await harness.run_all_tests()

    print(f"Total tests: {results['test_count']}")
    print(f"Mean precision: {results['aggregate_metrics']['mean_precision']:.3f}")
    print(f"Mean recall: {results['aggregate_metrics']['mean_recall']:.3f}")
    print(f"Mean F1: {results['aggregate_metrics']['mean_f1']:.3f}")

    await harness.save_results(results, "validation_results.json")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Creating Test Cases

### Step 1: Ingest Representative Documents

First, ingest documents that represent your use cases:

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source": "container",
    "container_metadata": {...}
  }'
```

Note the `document_id` from the response.

### Step 2: Create Test Cases

Create a test case JSON file:

```json
{
  "test_cases": [
    {
      "test_id": "container-vuln-001",
      "query": "Which containers have CVE-2024-1234?",
      "expected_documents": ["<document_id_from_step_1>"],
      "relevance_scores": {
        "<document_id_from_step_1>": 1.0
      },
      "category": "container",
      "description": "Test vulnerability search"
    }
  ]
}
```

### Step 3: Run Validation

```bash
curl -X POST http://localhost:8000/api/v1/validation/run
```

### Step 4: Review Results

```bash
curl http://localhost:8000/api/v1/validation/dashboard
```

---

## Interpreting Results

### High Precision, Low Recall

- System is conservative: returns only highly relevant results
- May be missing some relevant documents
- **Action**: Expand search scope, adjust ranking thresholds

### Low Precision, High Recall

- System is returning many results, including irrelevant ones
- Ranking quality may be poor
- **Action**: Improve ranking model, add filters

### Low NDCG

- Relevant documents are ranked poorly
- **Action**: Tune ranking weights, improve embeddings

### Low MRR

- First relevant result appears late in ranking
- **Action**: Boost top-k precision

---

## Best Practices

1. **Representative Test Cases**: Include diverse queries covering all use cases
2. **Graded Relevance**: Use relevance scores (0.0-1.0) for nuanced testing
3. **Regular Testing**: Run validation after each model update or data ingestion
4. **Category Breakdown**: Analyze metrics by category (container, incident, etc.)
5. **Trend Monitoring**: Track metrics over time to detect regressions
6. **A/B Testing**: Compare different ranking strategies using separate test runs

---

## Continuous Integration

Integrate validation into your CI/CD pipeline:

```yaml
# .github/workflows/validation.yml
name: Validation Tests

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run validation
        run: |
          curl -X POST ${{ secrets.API_URL }}/api/v1/validation/run
      - name: Check metrics
        run: |
          python scripts/check_validation_metrics.py --threshold 0.8
```

---

## Dashboard Visualization

The QA Dashboard provides:

1. **Aggregate Metrics**: Mean precision, recall, F1, NDCG, MRR, MAP
2. **Trend Charts**: Line charts showing metrics over time
3. **Per-Test Breakdown**: Table of individual test results
4. **Category Analysis**: Metrics grouped by category
5. **Failure Analysis**: Tests with low scores highlighted

---

## Troubleshooting

### Test Cases Not Loading

Check:
- File path is correct: `backend/validation/test_cases.json`
- JSON format is valid
- Test case IDs are unique

### Low Metrics

Check:
- Expected document IDs are correct
- Documents were successfully ingested
- Queries are representative of user intent

### Slow Execution

- Reduce test count or use sampling
- Increase Temporal worker concurrency
- Optimize retrieval pipeline

---

## Advanced Features

### Custom Metrics

Extend `MetricsResult` to add custom metrics:

```python
@staticmethod
def _compute_custom_metric(test_case: TestCase, result: RetrievalResult) -> float:
    # Your custom logic
    return score

# Add to compute_metrics()
```

### Weighted Categories

Weight categories differently:

```python
category_weights = {
    "container": 2.0,
    "incident": 1.5,
    "general": 1.0
}

weighted_f1 = sum(
    metric.f1_score * category_weights.get(category, 1.0)
    for metric, category in zip(metrics, categories)
) / sum(category_weights.values())
```

### Confidence Intervals

Compute confidence intervals for metrics:

```python
import scipy.stats as stats

def confidence_interval(values, confidence=0.95):
    mean = np.mean(values)
    sem = stats.sem(values)
    margin = sem * stats.t.ppf((1 + confidence) / 2, len(values) - 1)
    return mean - margin, mean + margin
```

---

## Next Steps

1. **Expand Test Suite**: Add test cases for all use cases
2. **Automate Collection**: Generate test cases from user queries
3. **Real-time Validation**: Run validation on production traffic
4. **Alerting**: Set up alerts for metric drops
5. **Feedback Loop**: Use validation results to improve retrieval
