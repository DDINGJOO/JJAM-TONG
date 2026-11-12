"""Real, temporary Git commits containing only synthetic community code."""
import hashlib
import os
import subprocess
from pathlib import Path

INITIAL = {
    "services/posts/PostController.java": "class PostController { Object list() { return service.list(); } }\n",
    "services/posts/PostService.java": "class PostService { Object list() { return repository.findAll(); } }\n",
    "services/comments/CommentService.java": "class CommentService { Object list() { return repository.findAll(); } }\n",
    "README.md": "Synthetic community repository; code is not compiled or executed.\n",
}


class Repository:
    def __init__(self, path):
        self.path, self.files, self.expected, self.number = Path(path), {}, {}, 0
        self.path.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Synthetic Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", "/dev/null")
        self.git("config", "core.autocrlf", "false")
        self.initial = self.commit(INITIAL)

    def git(self, *args, env=None):
        return subprocess.run(["git", "-C", str(self.path), *args], check=True,
                              capture_output=True, text=True, env=env, timeout=10).stdout.strip()

    def commit(self, changes, deleted=()):
        for path in deleted:
            (self.path / path).unlink()
            del self.files[path]
        for path, content in changes.items():
            target = self.path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            self.files[path] = content
        self.number += 1
        env = os.environ.copy()
        # Fixed fixture dates allow independent revision/index expectations.
        date = "2026-11-12T00:00:{:02d}+00:00".format(self.number)
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        self.git("add", "--all")
        self.git("commit", "-q", "-m", "synthetic fixture " + str(self.number), env=env)
        revision = self.git("rev-parse", "HEAD")
        self.expected[revision] = {p: hashlib.sha1(b"blob " + str(len(c.encode())).encode() + b"\0" + c.encode()).hexdigest()
                                   for p, c in self.files.items() if p.startswith("services/")}
        return revision
