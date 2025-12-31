/**
 * Sample Node.js/TypeScript database client using various libraries.
 */

import { Pool, Client } from 'pg';
import knex from 'knex';
import { Sequelize, Model, DataTypes } from 'sequelize';
import { PrismaClient } from '@prisma/client';
import { DataSource, Repository } from 'typeorm';
import { User } from './entities/User';

// pg (node-postgres) example
async function getUserWithPg(userId: number): Promise<any> {
    const pool = new Pool({
        user: 'postgres',
        host: 'localhost',
        database: 'mydb',
        password: 'secret',
        port: 5432,
    });

    try {
        const result = await pool.query(
            'SELECT id, username, email FROM test_schema.users WHERE id = $1',
            [userId]
        );
        return result.rows[0];
    } finally {
        await pool.end();
    }
}

// Knex example
const knexDb = knex({
    client: 'pg',
    connection: {
        host: 'localhost',
        user: 'postgres',
        password: 'secret',
        database: 'mydb',
    },
});

async function getOrdersWithKnex(userId: number) {
    return await knexDb('test_schema.orders')
        .select('id', 'total_amount', 'status')
        .where('user_id', userId)
        .orderBy('created_at', 'desc');
}

// Knex transaction example
async function createOrderWithKnex(userId: number, items: any[]) {
    return await knexDb.transaction(async (trx) => {
        const [order] = await trx('test_schema.orders')
            .insert({
                user_id: userId,
                total_amount: items.reduce((sum, item) => sum + item.price * item.qty, 0),
                status: 'pending',
            })
            .returning('*');

        await trx('test_schema.order_items').insert(
            items.map(item => ({
                order_id: order.id,
                product_name: item.name,
                quantity: item.qty,
                price: item.price,
            }))
        );

        return order;
    });
}

// Sequelize ORM example
const sequelize = new Sequelize('mydb', 'postgres', 'secret', {
    host: 'localhost',
    dialect: 'postgres',
    schema: 'test_schema',
});

class UserModel extends Model {}
UserModel.init(
    {
        id: {
            type: DataTypes.INTEGER,
            primaryKey: true,
            autoIncrement: true,
        },
        username: DataTypes.STRING(100),
        email: DataTypes.STRING(255),
    },
    {
        sequelize,
        tableName: 'users',
        schema: 'test_schema',
    }
);

async function getUserWithSequelize(userId: number) {
    return await UserModel.findByPk(userId);
}

// Sequelize raw query
async function searchUsersSequelize(searchTerm: string) {
    const [results] = await sequelize.query(
        `SELECT id, username, email
         FROM test_schema.users
         WHERE username ILIKE :searchTerm`,
        {
            replacements: { searchTerm: `%${searchTerm}%` },
        }
    );
    return results;
}

// TypeORM example
const dataSource = new DataSource({
    type: 'postgres',
    host: 'localhost',
    port: 5432,
    username: 'postgres',
    password: 'secret',
    database: 'mydb',
    entities: [User],
    schema: 'test_schema',
});

async function getUserWithTypeORM(userId: number) {
    await dataSource.initialize();
    const userRepository: Repository<User> = dataSource.getRepository(User);

    const user = await userRepository.findOne({
        where: { id: userId },
    });

    await dataSource.destroy();
    return user;
}

// TypeORM query builder
async function getOrdersByStatusTypeORM(status: string) {
    await dataSource.initialize();

    const orders = await dataSource
        .getRepository('Order')
        .createQueryBuilder('order')
        .where('order.status = :status', { status })
        .orderBy('order.created_at', 'DESC')
        .getMany();

    await dataSource.destroy();
    return orders;
}

// Prisma example
const prisma = new PrismaClient();

async function getUserWithPrisma(userId: number) {
    return await prisma.user.findUnique({
        where: { id: userId },
        include: { orders: true },
    });
}

// Prisma transaction
async function createOrderWithPrisma(userId: number, items: any[]) {
    return await prisma.$transaction(async (tx) => {
        const order = await tx.order.create({
            data: {
                userId,
                totalAmount: items.reduce((sum, item) => sum + item.price * item.qty, 0),
                status: 'pending',
            },
        });

        await tx.orderItem.createMany({
            data: items.map(item => ({
                orderId: order.id,
                productName: item.name,
                quantity: item.qty,
                price: item.price,
            })),
        });

        return order;
    });
}

// Raw SQL with pg Client
async function migrateDatabase() {
    const client = new Client({
        host: 'localhost',
        database: 'mydb',
        user: 'postgres',
        password: 'secret',
    });

    await client.connect();

    try {
        await client.query(`
            CREATE TABLE IF NOT EXISTS test_schema.migrations (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
        `);

        await client.query(`
            INSERT INTO test_schema.migrations (name)
            VALUES ($1)
            ON CONFLICT DO NOTHING
        `, ['create_users_table']);
    } finally {
        await client.end();
    }
}

// Locking example with pg
async function lockOrderForUpdate(orderId: string) {
    const client = new Client({
        host: 'localhost',
        database: 'mydb',
        user: 'postgres',
        password: 'secret',
    });

    await client.connect();

    try {
        await client.query('BEGIN');

        const result = await client.query(
            `SELECT id, user_id, total_amount, status
             FROM test_schema.orders
             WHERE id = $1
             FOR UPDATE`,
            [orderId]
        );

        // Do something with locked row
        await client.query('COMMIT');
        return result.rows[0];
    } catch (error) {
        await client.query('ROLLBACK');
        throw error;
    } finally {
        await client.end();
    }
}

export {
    getUserWithPg,
    getOrdersWithKnex,
    createOrderWithKnex,
    getUserWithSequelize,
    searchUsersSequelize,
    getUserWithTypeORM,
    getUserWithPrisma,
    createOrderWithPrisma,
    migrateDatabase,
    lockOrderForUpdate,
};
