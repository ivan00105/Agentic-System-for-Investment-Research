import argparse

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Serve the local research workspace and API.")
    parser.parse_args()
    uvicorn.run("research_assistant.api:create_app", factory=True, host="127.0.0.1", port=8000, workers=1)


if __name__ == "__main__":
    main()
