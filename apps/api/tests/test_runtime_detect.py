"""Runtime detection tests."""
from app.services.runtime_detect import detect_runtime, suggest_container_port


def reader_factory(files: dict[str, str]):
    def read(path: str):
        return files.get(path)

    return read


def test_detect_nextjs():
    files = {"package.json": "", "app/page.tsx": ""}
    reader = reader_factory({"package.json": '{"dependencies": {"next": "^15.0.0"}}'})
    detection = detect_runtime(files, reader)
    assert detection.runtime == "nextjs"
    assert suggest_container_port("nextjs") == 3000


def test_detect_laravel():
    files = ["composer.json", "artisan"]
    reader = reader_factory({
        "composer.json": '{"require": {"laravel/framework": "^11.0", "php": ">=8.2"}}'
    })
    detection = detect_runtime(files, reader)
    assert detection.runtime == "laravel"


def test_detect_fastapi():
    files = ["requirements.txt", "main.py"]
    reader = reader_factory({"requirements.txt": "fastapi==0.115.0\nuvicorn==0.32.0"})
    detection = detect_runtime(files, reader)
    assert detection.runtime == "fastapi"
    assert suggest_container_port("fastapi") == 8000


def test_detect_django():
    files = ["manage.py", "requirements.txt"]
    reader = reader_factory({"requirements.txt": "django==5.0"})
    detection = detect_runtime(files, reader)
    assert detection.runtime == "django"


def test_detect_go():
    files = ["go.mod", "main.go"]
    reader = reader_factory({"go.mod": "module example\n\ngo 1.22\n"})
    detection = detect_runtime(files, reader)
    assert detection.runtime == "go"
    assert detection.details["go_version"] == "1.22"


def test_detect_dockerfile_wins_over_compose():
    files = ["Dockerfile", "docker-compose.yml", "package.json"]
    reader = reader_factory({"package.json": "{}"})
    detection = detect_runtime(files, reader)
    assert detection.runtime == "compose"  # compose checked first by design


def test_detect_compose():
    files = ["docker-compose.yml", "src/main.py"]
    reader = reader_factory({})
    detection = detect_runtime(files, reader)
    assert detection.runtime == "compose"


def test_detect_static():
    files = ["index.html", "style.css"]
    reader = reader_factory({})
    detection = detect_runtime(files, reader)
    assert detection.runtime == "static"
    assert suggest_container_port("static") == 80


def test_detect_react_spa():
    files = ["package.json", "src/App.tsx"]
    reader = reader_factory({
        "package.json": '{"dependencies": {"react": "^18", "react-dom": "^18"}}'
    })
    detection = detect_runtime(files, reader)
    assert detection.runtime == "react"


def test_detect_angular_nuxt_nest():
    cases = [
        ('{"dependencies": {"@angular/core": "^18"}}', "angular"),
        ('{"dependencies": {"nuxt": "^3"}}', "nuxt"),
        ('{"dependencies": {"@nestjs/core": "^10"}}', "nestjs"),
        ('{"dependencies": {"express": "^4"}}', "express"),
    ]
    for pkg, expected in cases:
        detection = detect_runtime(["package.json"], reader_factory({"package.json": pkg}))
        assert detection.runtime == expected


def test_detect_unknown():
    detection = detect_runtime(["README.md"], reader_factory({}))
    assert detection.runtime == "unknown"
