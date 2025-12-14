const { PrismaClient } = require('@prisma/client');
const fs = require('fs');
const path = require('path');

const prisma = new PrismaClient();

async function setupDatabase() {
  try {
    console.log('🔧 Настройка базы данных...\n');

    // Читаем SQL миграцию
    const migrationPath = path.join(__dirname, '../prisma/migrations/init/migration.sql');
    const sql = fs.readFileSync(migrationPath, 'utf8');

    // Разбиваем на отдельные команды
    const commands = sql
      .split(';')
      .map(cmd => cmd.trim())
      .filter(cmd => cmd.length > 0 && !cmd.startsWith('--'));

    console.log(`Выполнение ${commands.length} SQL команд...\n`);

    // Выполняем каждую команду
    for (let i = 0; i < commands.length; i++) {
      const command = commands[i];
      if (command.trim()) {
        try {
          await prisma.$executeRawUnsafe(command);
          console.log(`✅ Команда ${i + 1}/${commands.length} выполнена`);
        } catch (error) {
          // Игнорируем ошибки "уже существует"
          if (error.message.includes('already exists') || error.message.includes('duplicate')) {
            console.log(`⚠️  Команда ${i + 1}/${commands.length} пропущена (уже существует)`);
          } else {
            console.error(`❌ Ошибка в команде ${i + 1}:`, error.message);
            throw error;
          }
        }
      }
    }

    console.log('\n✅ База данных успешно настроена!');
  } catch (error) {
    console.error('❌ Ошибка при настройке базы данных:', error);
    throw error;
  } finally {
    await prisma.$disconnect();
  }
}

setupDatabase();

