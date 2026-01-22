import csv
import os
from typing import Tuple

import numpy as np
from numpy.typing import NDArray

# Configuration
NUM_SAMPLES: int = 10
NUM_FEATURES: int = 5
RANDOM_SEED: int = 42

BASE_DIR: str = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW_DIR: str = os.path.join(BASE_DIR, "raw")
TARGET_DIR: str = os.path.join(BASE_DIR, "target")


def ensure_dirs() -> None:
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(TARGET_DIR, exist_ok=True)


def generate_data() -> Tuple[NDArray[np.float64], NDArray[np.int64]]:
    rng = np.random.default_rng(RANDOM_SEED)

    # Raw features
    X: NDArray[np.float64] = rng.normal(
        loc=0.0,
        scale=1.0,
        size=(NUM_SAMPLES, NUM_FEATURES),
    )

    # Example target: linear combination + noise, then binary label
    weights: NDArray[np.float64] = rng.uniform(-1, 1, size=NUM_FEATURES)
    y_continuous: NDArray[np.float64] = X @ weights + rng.normal(0, 0.5, size=NUM_SAMPLES)
    y: NDArray[np.int64] = (y_continuous > 0).astype(np.int64)

    return X, y


def save_raw(X: NDArray[np.float64]) -> None:
    raw_path: str = os.path.join(RAW_DIR, "data44.csv")
    with open(raw_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = [f"feature_{i}" for i in range(X.shape[1])]
        writer.writerow(header)
        writer.writerows(X)
    print(f"Saved raw data to {raw_path}")


def save_target(y: NDArray[np.int64]) -> None:
    target_path: str = os.path.join(TARGET_DIR, "labels44.csv")
    with open(target_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["label"])
        for value in y:
            writer.writerow([int(value)])
    print(f"Saved target data to {target_path}")


def main() -> None:
    ensure_dirs()
    X, y = generate_data()
    save_raw(X)
    save_target(y)


if __name__ == "__main__":
    main()
