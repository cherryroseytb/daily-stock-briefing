# 프로젝트 그라운드룰

## Git 푸시 규칙

로컬에서 커밋 후 푸시할 때, GitHub Actions 워크플로우가 원격 브랜치에 자동 커밋을 남겨 브랜치가 앞서 있는 경우가 발생한다.
이 경우 `git push` 전에 항상 `git pull --rebase origin main`으로 원격 커밋을 먼저 받아 정렬한 뒤 푸시한다.

```
git pull --rebase origin main && git push origin main
```

충돌이 발생하면 충돌을 해결한 뒤 `git rebase --continue`로 진행한다.
