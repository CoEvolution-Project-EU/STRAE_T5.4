# STR Assurance Engine - Tests

## Running Tests

### Prerequisites:
- Python 3.12 (recommended: 3.12.3)
- `pip`

To run the test suite, make sure your virtual environment is activated and dependencies are installed.

The tests use a mock storage client in order to perform unit tests without requiring a database connection.

Inside the `/code` directory:

### 1. Create and activate a virtual environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run tests
```bash
pytest
```

This will automatically discover and run all tests in the `tests/` directory.

Test output will be shown in your terminal.