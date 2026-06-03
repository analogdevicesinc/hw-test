#!/bin/bash
set -xeuo pipefail

json_="$(dirname -- "${BASH_SOURCE[0]}" )/sample/workflow-run.completed.json"

# workflow dispatch inputs
url=$(cat "$json_" | jq -r '.workflow_run.url' )
# url="https://api.github.com/repos/analogdevicesinc/linux/actions/runs/26873974794"
# url="https://api.github.com/repos/analogdevicesinc/linux/actions/runs/26882970726"
[[ "$url" =~ ^https://api.github.com/repos/.+/actions/runs/[0-9]+$ ]] || { echo "::error ::'$url' is not a github workflow_run api url" ; exit 1 ; }

# get context
json=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" "$url")
get() { echo "$json" | jq -r "$1"; }
owner=$(get '.repository.owner.login')
repository=$(get '.repository.name')
event=$(get '.event')
head_sha=$(get '.head_sha')

if [[ "$event" == "pull_request" ]]; then
  is_fork=$(get '.head_repository.fork')
  pr=$(get '.pull_requests[0].number // empty')

  if [[ "$is_fork" == "true" ]]; then
    pr=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
      "https://api.github.com/search/issues?q=repo:$owner/$repository+is:pr+sha:$head_sha" | jq -r '.items[0].number // empty')
    [[ -n "$pr" ]] || { echo "::error ::Pull request for sha ${head_sha} not found" ; exit 1 ; }
  fi
  pr_json=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    "https://api.github.com/repos/$owner/$repository/pulls/$pr")
  state=$(echo "$pr_json" | jq -r '.state')
  merge_commit_sha=$(echo "$pr_json" | jq -r '.merge_commit_sha // empty')
  target_branch=$(echo "$pr_json" | jq -r '.base.ref')
  base_branch_head_sha=$(echo "$pr_json" | jq -r '.base.sha')

  base_sha=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    "https://api.github.com/repos/$owner/$repository/compare/${base_branch_head_sha}...${head_sha}" | jq -r '.merge_base_commit.sha')
  changed_files=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    "https://api.github.com/repos/$owner/$repository/pulls/$pr/files" | jq -r '.[].filename')
else
  target_branch=$(get '.head_branch')
  base_sha=""
  for page in {1..3}; do
    event_json=$(wget -q -O- --header="Authorization: Bearer $GITHUB_TOKEN" \
      "https://api.github.com/repos/$owner/$repository/events?per_page=100&page=$page")
    base_sha=$(echo "$event_json" | jq -r --arg HEAD "$head_sha" '.[] | select(.type=="PushEvent" and .payload.head==$HEAD) | .payload.before' | head -1)
    if [[ -n "$base_sha" && "$base_sha" != "null" ]]; then
      break
    fi
  done
  [[ -n "$base_sha" ]] || { echo "::error ::Could not find PushEvent before sha for head_sha=$head_sha" ; exit 1 ; }
  changed_files=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    "https://api.github.com/repos/$owner/$repository/compare/${base_sha}...${head_sha}" | jq -r '.files[].filename')

  is_fork=
  pr=
  state=
  merge_commit_sha=
  base_branch_head_sha=
fi

out=$(mktemp)

# action outputs
{
  echo "owner=$owner"
  echo "repository=$repository"
  echo "is_fork=$is_fork"
  echo "pr=$pr"
  echo "state=$state"
  echo "branch=$target_branch" # always onto branch

  echo "head_sha=$head_sha"
  echo "base_sha=$base_sha"
  echo "merge_commit_sha=$merge_commit_sha" # empty is conflict

  echo "changed_files="
  echo "$changed_files"
  echo "base_branch_head_sha=$base_branch_head_sha"
} > "$out"

echo "$out"
cat "$out"
