const bcrypt = require('bcryptjs');

// Генерация хеша пароля для тестового пользователя
async function generatePasswordHash() {
  const password = 'admin123';
  const hash = await bcrypt.hash(password, 10);
  console.log('Хеш пароля для "admin123":');
  console.log(hash);
  console.log('\nSQL для создания пользователя:');
  console.log(`
INSERT INTO users (id, email, name, password, role, "createdAt", "updatedAt")
VALUES (
  'test-user-1',
  'admin@example.com',
  'Admin User',
  '${hash}',
  'ADMIN',
  NOW(),
  NOW()
);
  `);
}

generatePasswordHash();

