from flask import Flask, request, jsonify
from github import Github
from github.GithubException import UnknownObjectException, GithubException
import config
print(">> Using token:", repr(config.github_token))
print(">> Using user: ", repr(config.github_user))
app = Flask(__name__)

# Загрузка конфигурации
github_token = config.github_token
github_user = config.github_user

if not github_token:
    raise RuntimeError('Пожалуйста, установите github_token в config.py')

g = Github(github_token)

def get_repository(repo_name):
    """Возвращает объект репозитория или None, если не найден."""
    try:
        return g.get_repo(f"{github_user}/{repo_name}")
    except UnknownObjectException:
        return None

@app.route('/')
def index():
    return jsonify({
        "message": "API работает. Используйте /repo/<repo>/structure или другие доступные маршруты."
    })

# 1) Структура репозитория
@app.route('/repo/<repo>/structure', methods=['GET'])
def get_structure(repo):
    branch = request.args.get('branch', None)
    path = request.args.get('path', '')

    repository = get_repository(repo)
    if not repository:
        return jsonify({'error': f"Репозиторий '{repo}' не найден"}), 404

    try:
        branch_name = branch or repository.default_branch
        ref = repository.get_git_ref(f"heads/{branch_name}")
        sha = ref.object.sha

        tree = repository.get_git_tree(sha, recursive=True).tree

        def build_tree(base_path):
            items = []
            prefix = base_path.rstrip('/') + '/' if base_path else ''
            for element in tree:
                if (not base_path and '/' not in element.path) or \
                   (base_path and element.path.startswith(prefix) and element.path != base_path):
                    relative = element.path[len(prefix):] if base_path else element.path
                    if '/' not in relative:
                        items.append({'path': element.path, 'type': element.type})
            return items

        return jsonify({'structure': build_tree(path)})

    except UnknownObjectException:
        return jsonify({'error': f"Ветка '{branch_name}' не найдена"}), 404
    except GithubException as e:
        return jsonify({'error': f"Ошибка GitHub API: {e.data.get('message', str(e))}"}), e.status
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 2) Содержимое файла
@app.route('/repo/<repo>/file/<path:filepath>', methods=['GET'])
def get_file(repo, filepath):
    branch = request.args.get('branch', None)

    repository = get_repository(repo)
    if not repository:
        return jsonify({'error': f"Репозиторий '{repo}' не найден"}), 404

    try:
        content_file = repository.get_contents(filepath, ref=branch or repository.default_branch)
        return jsonify({
            'path': filepath,
            'content': content_file.decoded_content.decode('utf-8')
        })
    except UnknownObjectException:
        return jsonify({'error': f"Файл '{filepath}' не найден"}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 3) Создать новый файл
@app.route('/repo/<repo>/file', methods=['POST'])
def create_file(repo):
    raw = request.data.decode('utf-8')
    print(">> Raw POST data:", raw)
    try:
        data = request.get_json(force=True)
    except Exception as ex:
        return jsonify({'error': f'Неверный JSON: {ex}'}), 400

    branch = data.get('branch', None)
    file_path = data.get('path', '')
    file_name = data.get('name')
    content = data.get('content', '')
    message = data.get('message', 'Создание нового файла через API')

    repository = get_repository(repo)
    if not repository:
        return jsonify({'error': f"Репозиторий '{repo}' не найден"}), 404

    if not file_name:
        return jsonify({'error': 'Поле "name" обязательно'}), 400

    try:
        full_path = f"{file_path.rstrip('/')}/{file_name}" if file_path else file_name
        repository.create_file(full_path, message, content, branch=branch or repository.default_branch)
        return jsonify({'message': 'Файл создан', 'path': full_path}), 201
    except UnknownObjectException:
        return jsonify({'error': 'Не удалось создать файл: путь или ветка не найдены'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 4) Просмотреть все файлы со вcех вложений и их содержимое
@app.route('/repo/<repo>/all', methods=['GET'])
def get_all(repo):
    branch = request.args.get('branch', None)
    repository = get_repository(repo)
    if not repository:
        return jsonify({'error': f"Репозиторий '{repo}' не найден"}), 404

    # получаем SHA нужной ветки
    branch_name = branch or repository.default_branch
    ref = repository.get_git_ref(f"heads/{branch_name}")
    sha = ref.object.sha

    # полное дерево
    tree = repository.get_git_tree(sha, recursive=True).tree

    files = []
    for element in tree:
        if element.type == 'blob':
            try:
                content_file = repository.get_contents(element.path, ref=branch_name)
                text = content_file.decoded_content.decode('utf-8')
            except Exception:
                text = None
            files.append({'path': element.path, 'content': text})

    return jsonify({'files': files})


# 5) Обновить существующий файл
@app.route('/repo/<repo>/file/<path:filepath>', methods=['PUT'])
def update_file(repo, filepath):
    try:
        data = request.get_json(force=True)
    except Exception as ex:
        return jsonify({'error': f'Неверный JSON: {ex}'}), 400

    branch = data.get('branch', None)
    new_content = data.get('content', '')
    message = data.get('message', 'Update file via API')

    repository = get_repository(repo)
    if not repository:
        return jsonify({'error': f"Репозиторий '{repo}' не найден"}), 404

    try:
        # получаем текущий файл, чтобы взять его SHA
        file_obj = repository.get_contents(filepath, ref=branch or repository.default_branch)
        repository.update_file(
            path=filepath,
            message=message,
            content=new_content,
            sha=file_obj.sha,
            branch=branch or repository.default_branch
        )
        return jsonify({'message': 'Файл обновлён', 'path': filepath})
    except UnknownObjectException:
        return jsonify({'error': f"Файл '{filepath}' не найден"}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 6) Удалить файл
@app.route('/repo/<repo>/file/<path:filepath>', methods=['DELETE'])
def delete_file(repo, filepath):
    try:
        data = request.get_json(force=True)
    except Exception as ex:
        return jsonify({'error': f'Неверный JSON: {ex}'}), 400

    branch = data.get('branch', None)
    message = data.get('message', 'Delete file via API')

    repository = get_repository(repo)
    if not repository:
        return jsonify({'error': f"Репозиторий '{repo}' не найден"}), 404

    try:
        # получаем SHA файла для удаления
        file_obj = repository.get_contents(filepath, ref=branch or repository.default_branch)
        repository.delete_file(
            path=filepath,
            message=message,
            sha=file_obj.sha,
            branch=branch or repository.default_branch
        )
        return jsonify({'message': 'Файл удалён', 'path': filepath})
    except UnknownObjectException:
        return jsonify({'error': f"Файл '{filepath}' не найден"}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
