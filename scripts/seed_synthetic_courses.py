"""Seed 6 synthetic course records for RAG ranking experiments.

These are NOT real NEU catalog content — they are plausible-style placeholders
crafted to have differentiated vocabulary so bge-m3 can pull them apart.
Each row's course_id is prefixed `synth-` and `source_review_ids` includes
"synthetic_seed" so it's trivially removable:

    DELETE FROM courses        WHERE course_id LIKE 'synth-%';
    DELETE FROM course_aliases WHERE primary_course_id LIKE 'synth-%';

After running this script:
    python scripts/rebuild_faiss.py    # ~80s incl. model load
    # then run docs/rag_smoke_results.md §5 query battery

PLAN §3 candidate list informed the picks; coverage is intentionally spread:
  CS 5800 Algorithms        — pure algorithm theory
  DS 5220 Supervised ML     — regression / classification / NN
  DS 5230 Unsupervised ML   — clustering / dim-reduction
  CS 6140 Machine Learning  — statistical learning theory
  INFO 6105 Data Science Eng — data pipelines / engineering
  MATH 7243 Math of Data    — linear algebra / convex optimization
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db.connection import connect  # noqa: E402
from db.repository import CourseRepository  # noqa: E402
from schemas.course import Course, DeliveryMode  # noqa: E402
from scripts.init_db import init_database  # noqa: E402

SYNTHETIC_MARKER = "synthetic_seed_2026_04_30"


SYNTHETIC_COURSES: list[dict] = [
    {
        "course_id": "synth-cs-5800",
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
        "credits": 4,
        "delivery_mode": DeliveryMode.IN_PERSON,
        "topics": [
            "asymptotic analysis", "big-O notation", "recurrence relations",
            "divide and conquer", "dynamic programming", "greedy algorithms",
            "graph algorithms", "BFS DFS", "shortest paths Dijkstra",
            "minimum spanning trees", "NP-completeness", "approximation algorithms",
        ],
        "raw_text": """\
Course: CS 5800 Algorithms
Term: Spring 2026 | Credits: 4 | Format: In-person

This course covers the design and analysis of algorithms. Topics include
asymptotic analysis (big-O, big-Omega), recurrence relations and the master
theorem, divide-and-conquer (merge sort, Strassen's algorithm), dynamic
programming (longest common subsequence, knapsack, sequence alignment),
greedy algorithms (Huffman coding, scheduling), graph algorithms
(BFS, DFS, Dijkstra's shortest paths, Bellman-Ford, Floyd-Warshall, MST
via Kruskal/Prim), network flow, NP-completeness and reductions,
and approximation algorithms.

Prerequisites: data structures (CS 5008 or equivalent), discrete math.
No machine learning content; pure algorithms.

[synthetic_seed for ranking tests, not real NEU catalog content]
""",
    },
    {
        "course_id": "synth-ds-5220",
        "primary_code": "DS 5220",
        "primary_name": "Supervised Machine Learning and Learning Theory",
        "credits": 4,
        "delivery_mode": DeliveryMode.HYBRID,
        "topics": [
            "linear regression", "logistic regression", "gradient descent",
            "feature engineering", "regularization L1 L2", "cross-validation",
            "decision trees", "random forests", "gradient boosting XGBoost",
            "neural networks backpropagation", "convolutional networks",
            "supervised learning evaluation", "ROC AUC precision recall",
        ],
        "raw_text": """\
Course: DS 5220 Supervised Machine Learning and Learning Theory
Term: Spring 2026 | Credits: 4 | Format: Hybrid

Practical and theoretical foundations of supervised learning. Covers
linear and logistic regression with gradient descent and stochastic
gradient descent, regularization (L1/L2/elastic net), cross-validation
strategies, decision trees, random forests, gradient boosting (XGBoost,
LightGBM), neural networks with backpropagation, convolutional networks
for image data. Strong emphasis on model evaluation: train/validation/test
splits, ROC curves, AUC, precision-recall, calibration, fairness metrics.
Hands-on projects in scikit-learn and PyTorch.

Prerequisites: probability and statistics, Python proficiency, linear algebra.

[synthetic_seed for ranking tests, not real NEU catalog content]
""",
    },
    {
        "course_id": "synth-ds-5230",
        "primary_code": "DS 5230",
        "primary_name": "Unsupervised Machine Learning and Data Mining",
        "credits": 4,
        "delivery_mode": DeliveryMode.IN_PERSON,
        "topics": [
            "k-means clustering", "hierarchical clustering", "DBSCAN",
            "Gaussian mixture models EM algorithm",
            "principal component analysis PCA", "t-SNE UMAP",
            "matrix factorization", "association rule mining",
            "anomaly detection", "topic modeling LDA",
            "dimensionality reduction",
        ],
        "raw_text": """\
Course: DS 5230 Unsupervised Machine Learning and Data Mining
Term: Spring 2026 | Credits: 4 | Format: In-person

Covers techniques for finding structure in unlabeled data. Topics include
clustering (k-means, k-medoids, hierarchical agglomerative, DBSCAN, spectral
clustering), Gaussian mixture models with EM algorithm, dimensionality
reduction (PCA, kernel PCA, t-SNE, UMAP, autoencoders), matrix factorization
(SVD, NMF), association rule mining (Apriori, FP-growth), anomaly and
outlier detection, topic modeling (Latent Dirichlet Allocation LDA),
and recommendation systems via collaborative filtering.

No supervised methods covered — see DS 5220 for that.

Prerequisites: probability, linear algebra, basic Python.

[synthetic_seed for ranking tests, not real NEU catalog content]
""",
    },
    {
        "course_id": "synth-cs-6140",
        "primary_code": "CS 6140",
        "primary_name": "Machine Learning",
        "credits": 4,
        "delivery_mode": DeliveryMode.IN_PERSON,
        "topics": [
            "PAC learning", "VC dimension", "Rademacher complexity",
            "kernel methods support vector machines SVM",
            "Bayesian learning maximum likelihood MAP",
            "expectation maximization EM",
            "graphical models hidden Markov models HMM",
            "reinforcement learning Q-learning",
            "online learning regret bounds",
            "ensemble methods boosting AdaBoost",
        ],
        "raw_text": """\
Course: CS 6140 Machine Learning
Term: Spring 2026 | Credits: 4 | Format: In-person

A rigorous treatment of machine learning theory and algorithms. Topics
include PAC learning framework, VC dimension and Rademacher complexity,
generalization bounds, kernel methods and reproducing kernel Hilbert
spaces (RKHS), support vector machines (SVM), Bayesian learning with
maximum likelihood and MAP estimation, expectation-maximization (EM)
algorithm, probabilistic graphical models (Bayesian networks, Markov
random fields, hidden Markov models), reinforcement learning fundamentals
(Q-learning, policy gradient), online learning with regret bounds,
ensemble methods (bagging, AdaBoost).

More theoretical than DS 5220. Heavy on math derivations.

Prerequisites: real analysis recommended, strong probability + linear algebra.

[synthetic_seed for ranking tests, not real NEU catalog content]
""",
    },
    {
        "course_id": "synth-info-6105",
        "primary_code": "INFO 6105",
        "primary_name": "Data Science Engineering Methods and Tools",
        "credits": 4,
        "delivery_mode": DeliveryMode.HYBRID,
        "topics": [
            "ETL pipelines extract transform load",
            "Apache Spark distributed data processing",
            "data warehousing OLAP",
            "schema design star schema snowflake",
            "Apache Kafka streaming",
            "Airflow workflow orchestration",
            "containerization Docker Kubernetes",
            "cloud platforms AWS GCP",
            "data quality testing",
        ],
        "raw_text": """\
Course: INFO 6105 Data Science Engineering Methods and Tools
Term: Spring 2026 | Credits: 4 | Format: Hybrid

Engineering side of data science: building production-grade pipelines
from raw data to dashboards and ML inputs. Topics include ETL
(extract-transform-load) patterns, Apache Spark for distributed batch
processing, Apache Kafka for streaming, data warehousing with star/snowflake
schemas, OLAP cubes, Airflow for workflow orchestration, containerization
(Docker, Kubernetes), cloud-native deployment on AWS/GCP, data quality
testing (Great Expectations), and basic MLOps (model versioning, monitoring).

This is NOT a machine learning course — it's the plumbing that makes
ML possible at scale.

Prerequisites: Python and SQL proficiency.

[synthetic_seed for ranking tests, not real NEU catalog content]
""",
    },
    {
        "course_id": "synth-math-7243",
        "primary_code": "MATH 7243",
        "primary_name": "Mathematics of Data Models",
        "credits": 4,
        "delivery_mode": DeliveryMode.IN_PERSON,
        "topics": [
            "linear algebra eigenvalues SVD",
            "convex optimization Lagrangian duality",
            "probability theory measure-theoretic",
            "random variables expectation variance",
            "concentration inequalities Hoeffding Chernoff",
            "stochastic processes martingales",
            "information theory entropy KL divergence",
            "Markov chains stationary distributions",
        ],
        "raw_text": """\
Course: MATH 7243 Mathematics of Data Models
Term: Spring 2026 | Credits: 4 | Format: In-person

The mathematical foundations underlying modern data analysis. Linear
algebra emphasizing eigenvalue decompositions, singular value decomposition
(SVD), Moore-Penrose pseudoinverse, projections onto subspaces. Convex
optimization: convex sets and functions, Lagrangian duality, KKT
conditions, gradient and subgradient methods. Probability theory at a
measure-theoretic level: sigma-algebras, random variables, expectation,
concentration inequalities (Markov, Chebyshev, Hoeffding, Chernoff).
Stochastic processes including martingales and Markov chains with stationary
distribution analysis. Information theory: entropy, KL divergence, mutual
information. No statistics or machine learning content directly.

Prerequisites: undergraduate real analysis and linear algebra.

[synthetic_seed for ranking tests, not real NEU catalog content]
""",
    },
]


def seed(db_path: str | Path) -> dict[str, int]:
    """Insert synthetic courses + mark indexed (so retriever returns them).

    Idempotent via upsert. Returns counts: {inserted, already_present}.
    """
    init_database(db_path)
    conn = connect(db_path)
    counts = {"upserted": 0}
    try:
        repo = CourseRepository(conn)
        for spec in SYNTHETIC_COURSES:
            course = Course(
                course_id=spec["course_id"],
                primary_code=spec["primary_code"],
                primary_name=spec["primary_name"],
                credits=spec["credits"],
                term="Spring 2026",
                delivery_mode=spec["delivery_mode"],
                topics_covered=spec["topics"],
                source_review_ids=[SYNTHETIC_MARKER],
                extraction_confidence=0.5,  # synthetic, low confidence
            )
            repo.upsert(course, raw_text=spec["raw_text"])
            counts["upserted"] += 1

            # mark_indexed (transition pending -> indexed). Strict: only works
            # if status is currently 'pending', which upsert just set.
            try:
                repo.mark_indexed(spec["course_id"])
            except ValueError:
                # already indexed from a prior run; that's fine, upsert reset
                # to pending then... wait, upsert DOES reset to pending.
                # So this should always work. If not, surface the error.
                raise

        conn.commit()
    finally:
        conn.close()
    return counts


def main() -> int:
    from config import settings  # noqa: PLC0415
    db_path = settings.sqlite_path
    print(f"=> seeding {len(SYNTHETIC_COURSES)} synthetic courses to {db_path}")
    counts = seed(db_path)
    print(f"   upserted: {counts['upserted']}")
    print()
    print("Next: rebuild FAISS")
    print("    uv run python scripts/rebuild_faiss.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
