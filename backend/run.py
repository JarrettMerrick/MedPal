import os
import uvicorn

if __name__ == "__main__":
    # 生产环境不启用reload，开发环境可通过环境变量控制
    reload_mode = os.environ.get("UVICORN_RELOAD", "false").lower() == "true"
    uvicorn.run("app.main:app", host="0.0.0.0", port=5000, reload=reload_mode)
