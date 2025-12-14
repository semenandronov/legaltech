// Скрипт для проверки готовности проекта к сборке
const fs = require('fs');
const path = require('path');

console.log('🔍 Проверка готовности проекта к сборке...\n');

const checks = [];

// Проверка package.json
if (fs.existsSync('package.json')) {
  const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
  checks.push({ name: 'package.json', status: true });
  
  // Проверка обязательных скриптов
  const requiredScripts = ['dev', 'build', 'start'];
  const hasAllScripts = requiredScripts.every(script => pkg.scripts && pkg.scripts[script]);
  checks.push({ name: 'Скрипты в package.json', status: hasAllScripts });
} else {
  checks.push({ name: 'package.json', status: false });
}

// Проверка tsconfig.json
checks.push({ name: 'tsconfig.json', status: fs.existsSync('tsconfig.json') });

// Проверка next.config.js
checks.push({ name: 'next.config.js', status: fs.existsSync('next.config.js') });

// Проверка prisma schema
checks.push({ name: 'prisma/schema.prisma', status: fs.existsSync('prisma/schema.prisma') });

// Проверка основных директорий
const requiredDirs = ['app', 'components', 'lib', 'prisma'];
requiredDirs.forEach(dir => {
  checks.push({ name: `Директория ${dir}/`, status: fs.existsSync(dir) });
});

// Проверка .env.example
checks.push({ name: '.env.example', status: fs.existsSync('.env.example') });

// Вывод результатов
let allPassed = true;
checks.forEach(check => {
  const icon = check.status ? '✅' : '❌';
  console.log(`${icon} ${check.name}`);
  if (!check.status) allPassed = false;
});

console.log('\n' + '='.repeat(50));
if (allPassed) {
  console.log('✅ Все проверки пройдены! Проект готов к сборке.');
  process.exit(0);
} else {
  console.log('❌ Некоторые проверки не пройдены. Исправьте ошибки перед сборкой.');
  process.exit(1);
}

