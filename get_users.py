
import requests
import json

def get_users():
    url = "https://jsonplaceholder.typicode.com/users"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        users = response.json()
        print(json.dumps(users, indent=2))
    except requests.exceptions.RequestException as e:
        print(f"Error fetching users: {e}")

if __name__ == "__main__":
    get_users()
