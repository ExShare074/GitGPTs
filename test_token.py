from github import Github
import config

g = Github(config.github_token)
try:
    user = g.get_user().login
    print("Authenticated as:", user)
    print("Repos:", [r.name for r in g.get_user().get_repos()][:5])
except Exception as e:
    print("Error fetching user:", e)
