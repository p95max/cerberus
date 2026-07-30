from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "backend"]
DEMO_EVENT_SUBMISSION_ENABLED = env_bool("DEMO_EVENT_SUBMISSION_ENABLED", "true")  # noqa: F405
MOCK_BARRIER_CONTROL_ENABLED = env_bool("MOCK_BARRIER_CONTROL_ENABLED", "true")  # noqa: F405
