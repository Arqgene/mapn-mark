import sys
import os
import unittest
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from models.db import init_db, get_db_connection

class UserManagementTest(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()
        init_db()
        
        # Ensure test admin exists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE email LIKE 'test_%@example.com'")
        cursor.execute("INSERT INTO users (email, password, name, role) VALUES ('test_admin@example.com', 'pass', 'Admin', 'admin') ON DUPLICATE KEY UPDATE role='admin'")
        cursor.execute("INSERT INTO users (email, password, name, role) VALUES ('test_user@example.com', 'pass', 'User', 'user') ON DUPLICATE KEY UPDATE role='user'")
        conn.commit()
        cursor.close()
        conn.close()

    def login(self, email, password):
        return self.app.post('/login', data=dict(
            email=email,
            password=password
        ), follow_redirects=True)

    def test_admin_get_users(self):
        self.login('test_admin@example.com', 'pass')
        response = self.app.get('/api/users')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(isinstance(data, list))
        self.assertTrue(any(u['email'] == 'test_admin@example.com' for u in data))

    def test_user_cannot_get_users(self):
        self.login('test_user@example.com', 'pass')
        response = self.app.get('/api/users')
        self.assertEqual(response.status_code, 403)

    def test_admin_create_delete_user(self):
        self.login('test_admin@example.com', 'pass')
        
        # Create
        new_user = {
            'email': 'test_temp@example.com',
            'password': 'pass',
            'name': 'Temp User',
            'role': 'user'
        }
        response = self.app.post('/api/create-user', 
                                 data=json.dumps(new_user),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 201)

        # Verify in list
        response = self.app.get('/api/users')
        data = json.loads(response.data)
        self.assertTrue(any(u['email'] == 'test_temp@example.com' for u in data))

        # Delete
        response = self.app.post('/api/delete-user',
                                 data=json.dumps({'email': 'test_temp@example.com'}),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 200)

        # Verify gone
        response = self.app.get('/api/users')
        data = json.loads(response.data)
        self.assertFalse(any(u['email'] == 'test_temp@example.com' for u in data))

if __name__ == '__main__':
    unittest.main()
