import sys
import os
import unittest
import json
import time

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from models.db import init_db, get_db_connection

class MultiTenancyTest(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()
        init_db()
        
        # Helper to clear test data
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("DELETE FROM users WHERE email LIKE 'test_%@example.com'")
        cursor.execute("DELETE FROM institutions WHERE name LIKE 'Test Inst%'")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        # Create Super Admin
        cursor.execute("INSERT INTO users (email, password, name, role, username) VALUES ('test_super@example.com', 'pass', 'Super Admin', 'super_admin', 'superadmin') ON DUPLICATE KEY UPDATE role='super_admin'")
        conn.commit()
        cursor.close()
        conn.close()

    def login(self, email, password):
        return self.app.post('/login', data=dict(
            email=email,
            password=password
        ), follow_redirects=True)

    def test_full_flow(self):
        # 1. Login as Super Admin
        self.login('test_super@example.com', 'pass')

        # 2. Create Institution with Limits
        # User Limit: 2, Admin Limit: 1
        inst_data = {'name': 'Test Inst A', 'user_limit': 2, 'admin_limit': 1}
        resp = self.app.post('/api/create-institution', data=json.dumps(inst_data), content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        
        # Get Inst ID
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM institutions WHERE name='Test Inst A'")
        inst_id = cursor.fetchone()['id']
        cursor.close()
        conn.close()

        # 3. Create Inst Admin for Test Inst A
        # Super Admin creating an admin for an institution
        admin_data = {
            'email': 'test_admin_a@example.com',
            'username': 'admin_a',
            'password': 'pass',
            'name': 'Admin A',
            'role': 'admin',
            'institution_id': inst_id
        }
        resp = self.app.post('/api/create-user', data=json.dumps(admin_data), content_type='application/json')
        self.assertEqual(resp.status_code, 201)

        # 4. Login as Inst Admin A
        self.app.get('/logout')
        self.login('test_admin_a@example.com', 'pass')

        # 5. Create Users (Within Limit)
        # Create User 1
        u1_data = {'email': 'u1@example.com', 'username': 'u1', 'password': 'pass', 'name': 'U1', 'role': 'user'}
        resp = self.app.post('/api/create-user', data=json.dumps(u1_data), content_type='application/json')
        self.assertEqual(resp.status_code, 201)

        # Create User 2
        u2_data = {'email': 'u2@example.com', 'username': 'u2', 'password': 'pass', 'name': 'U2', 'role': 'user'}
        resp = self.app.post('/api/create-user', data=json.dumps(u2_data), content_type='application/json')
        self.assertEqual(resp.status_code, 201)

        # 6. Create User 3 (Exceed Limit) - Limit is 2
        u3_data = {'email': 'u3@example.com', 'username': 'u3', 'password': 'pass', 'name': 'U3', 'role': 'user'}
        resp = self.app.post('/api/create-user', data=json.dumps(u3_data), content_type='application/json')
        self.assertEqual(resp.status_code, 409)
        self.assertIn("limit reached", resp.get_json()['error'])

        # 7. Create Another Admin (Exceed Admin Limit) - Limit is 1 (already used by self?)
        # Wait, if I am Admin A, I am already 1 admin. Limit is 1. So I shouldn't be able to create another admin.
        # My backend logic: "SELECT COUNT(*) ... WHERE role='admin'". Includes self.
        u_admin2_data = {'email': 'admin2@example.com', 'username': 'admin2', 'password': 'pass', 'name': 'Admin 2', 'role': 'admin'}
        resp = self.app.post('/api/create-user', data=json.dumps(u_admin2_data), content_type='application/json')
        self.assertEqual(resp.status_code, 409) # Should fail
        
        # 8. Try to create Super Admin (Forbidden)
        u_super_data = {'email': 'fake_super@example.com', 'username': 'fake_super', 'password': 'pass', 'name': 'Fake Super', 'role': 'super_admin'}
        resp = self.app.post('/api/create-user', data=json.dumps(u_super_data), content_type='application/json')
        self.assertEqual(resp.status_code, 403)

        # 9. Verify Isolation
        # Inst Admin should only see their own users (U1, U2, Self)
        resp = self.app.get('/api/users')
        data = json.loads(resp.data)
        users = data['users']
        self.assertEqual(len(users), 3) # Admin A + U1 + U2
        
        # Logout
        self.app.get('/logout')
        
    def test_super_admin_view(self):
        self.login('test_super@example.com', 'pass')
        resp = self.app.get('/api/users')
        data = json.loads(resp.data)
        users = data['users']
        # Should see Super Admin + Admin A + U1 + U2 (from previous test run likely persisting in DB or if I ran sequentially)
        # Actually setUp clears specific patterns.
        # But let's just check I can see my own super admin user at least.
        self.assertTrue(any(u['email'] == 'test_super@example.com' for u in users))

if __name__ == '__main__':
    unittest.main()
