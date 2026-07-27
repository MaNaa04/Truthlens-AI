why are we storing/writing data/ responses to our database?
=> {
    Why? Your project has a local analytics JSON logger (for http://localhost:8000/analytics) and a production MongoDB audit logs database for per-user history tracking (accessed via GET /api/history). MongoDB stores user-scoped query/result logs asynchronously via BackgroundTasks to prevent database I/O from affecting request latency.
}

docker solves it -> mapping to some folder called data.
-> we need to map local data folder to the container's data folder using a "Volume"
---------------------------------------------------------------
NOTE:
The API caching (implemented in app/core/cache.py) defaults to Redis in production. When Redis is enabled, keys are cached globally across all instances. If Redis is unavailable or disabled, the application falls back gracefully to a thread-safe, local, in-memory TTLCache.
------------------------------------------------------