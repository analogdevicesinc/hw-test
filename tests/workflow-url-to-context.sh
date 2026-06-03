#!/bin/bash
set -xeuo pipefail

json_="$(dirname -- "${BASH_SOURCE[0]}" )/sample/workflow-run.completed.json"

# workflow dispatch inputs
# https://api.github.com/repos/analogdevicesinc/linux/actions/runs/26873974794
url=$(cat "$json_" | jq -r '.workflow_run.url' )
[[ "$url" =~ ^https://api.github.com/repos/.+/actions/runs/[0-9]+$ ]] || { echo "::error ::'$url' is not a github workflow_run api url" ; exit 1 ; }

# get context
json=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" "$url")
get() { echo "$json" | jq -r "$1"; }
org=$(get '.repository.owner.login')
repository=$(get '.repository.name')
is_fork=$(get '.head_repository.fork')
pr=$(get '.pull_requests[0].number // empty')
head_sha=$(get '.head_sha')

if [[ "$is_fork" == "true" ]]; then
  pr=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    "https://api.github.com/search/issues?q=repo:$org/$repository+is:pr+sha:$head_sha" | jq -r '.items[0].number // empty')
  [[ -n "$pr" ]] || { echo "::error ::Pull request for sha ${head_sha} not found" ; exit 1 ; }
fi
pr_json=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/$org/$repository/pulls/$pr")
state=$(echo "$pr_json" | jq -r '.state')
merge_commit_sha=$(echo "$pr_json" | jq -r '.merge_commit_sha // empty')
base_branch_head_sha=$(echo "$pr_json" | jq -r '.base.sha')

base_sha=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/$org/$repository/compare/${base_branch_head_sha}...${head_sha}" | jq -r '.merge_base_commit.sha')
changed_files=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/$org/$repository/pulls/$pr/files" | jq -r '.[].filename')

out=$(mktemp)

# action outputs
{
  echo "org=$org"
  echo "repository=$repository"
  echo "is_fork=$is_fork"
  echo "pr=$pr"
  echo "state=$state"

  echo "head_sha=$head_sha"
  echo "base_sha=$base_sha"
  echo "merge_commit_sha=$merge_commit_sha" # empty is conflict

  echo "changed_files="
  echo "$changed_files"
  echo "base_branch_head_sha=$base_branch_head_sha"
} > "$out"

echo "$out"
cat "$out"
