// Sample Go database client using various libraries
package main

import (
    "context"
    "database/sql"
    "fmt"
    "time"

    "github.com/jackc/pgx/v5"
    "github.com/jackc/pgx/v5/pgxpool"
    "gorm.io/driver/postgres"
    "gorm.io/gorm"
    _ "github.com/lib/pq"
)

// User model for GORM
type User struct {
    ID        int       `gorm:"primaryKey"`
    Username  string    `gorm:"size:100"`
    Email     string    `gorm:"size:255"`
    CreatedAt time.Time
    UpdatedAt time.Time
}

func (User) TableName() string {
    return "test_schema.users"
}

// database/sql example with lib/pq
func getUserWithDatabaseSQL(userID int) (*User, error) {
    connStr := "user=postgres password=secret dbname=mydb host=localhost sslmode=disable"
    db, err := sql.Open("postgres", connStr)
    if err != nil {
        return nil, err
    }
    defer db.Close()

    var user User
    err = db.QueryRow(
        "SELECT id, username, email FROM test_schema.users WHERE id = $1",
        userID,
    ).Scan(&user.ID, &user.Username, &user.Email)

    if err != nil {
        return nil, err
    }
    return &user, nil
}

// pgx connection pool example
func getOrdersWithPgx(ctx context.Context, userID int) ([]map[string]interface{}, error) {
    pool, err := pgxpool.New(ctx, "postgres://postgres:secret@localhost:5432/mydb")
    if err != nil {
        return nil, err
    }
    defer pool.Close()

    rows, err := pool.Query(ctx,
        `SELECT id, total_amount, status
         FROM test_schema.orders
         WHERE user_id = $1
         ORDER BY created_at DESC`,
        userID,
    )
    if err != nil {
        return nil, err
    }
    defer rows.Close()

    var orders []map[string]interface{}
    for rows.Next() {
        values, err := rows.Values()
        if err != nil {
            return nil, err
        }

        order := map[string]interface{}{
            "id":           values[0],
            "totalAmount":  values[1],
            "status":       values[2],
        }
        orders = append(orders, order)
    }

    return orders, rows.Err()
}

// pgx transaction example
func createOrderWithPgx(ctx context.Context, userID int, totalAmount float64) (string, error) {
    conn, err := pgx.Connect(ctx, "postgres://postgres:secret@localhost:5432/mydb")
    if err != nil {
        return "", err
    }
    defer conn.Close(ctx)

    tx, err := conn.Begin(ctx)
    if err != nil {
        return "", err
    }
    defer tx.Rollback(ctx)

    var orderID string
    err = tx.QueryRow(ctx,
        `INSERT INTO test_schema.orders (user_id, total_amount, status)
         VALUES ($1, $2, 'pending')
         RETURNING id`,
        userID, totalAmount,
    ).Scan(&orderID)

    if err != nil {
        return "", err
    }

    if err := tx.Commit(ctx); err != nil {
        return "", err
    }

    return orderID, nil
}

// GORM example
func getUserWithGORM(userID int) (*User, error) {
    dsn := "host=localhost user=postgres password=secret dbname=mydb port=5432 sslmode=disable"
    db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
    if err != nil {
        return nil, err
    }

    var user User
    result := db.First(&user, userID)
    if result.Error != nil {
        return nil, result.Error
    }

    return &user, nil
}

// GORM raw SQL
func searchUsersGORM(searchTerm string) ([]User, error) {
    dsn := "host=localhost user=postgres password=secret dbname=mydb port=5432 sslmode=disable"
    db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
    if err != nil {
        return nil, err
    }

    var users []User
    result := db.Raw(
        `SELECT id, username, email
         FROM test_schema.users
         WHERE username ILIKE ?`,
        "%"+searchTerm+"%",
    ).Scan(&users)

    if result.Error != nil {
        return nil, result.Error
    }

    return users, nil
}

// GORM transaction
func createOrderWithGORM(userID int, totalAmount float64) (int, error) {
    dsn := "host=localhost user=postgres password=secret dbname=mydb port=5432 sslmode=disable"
    db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
    if err != nil {
        return 0, err
    }

    type Order struct {
        ID          int
        UserID      int
        TotalAmount float64
        Status      string
    }

    var orderID int
    err = db.Transaction(func(tx *gorm.DB) error {
        order := Order{
            UserID:      userID,
            TotalAmount: totalAmount,
            Status:      "pending",
        }

        if err := tx.Table("test_schema.orders").Create(&order).Error; err != nil {
            return err
        }

        orderID = order.ID
        return nil
    })

    return orderID, err
}

// DDL operation
func createAuditTable() error {
    connStr := "user=postgres password=secret dbname=mydb host=localhost sslmode=disable"
    db, err := sql.Open("postgres", connStr)
    if err != nil {
        return err
    }
    defer db.Close()

    _, err = db.Exec(`
        CREATE TABLE IF NOT EXISTS test_schema.audit_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES test_schema.users(id),
            action VARCHAR(100),
            timestamp TIMESTAMPTZ DEFAULT now()
        )
    `)

    return err
}

// Locking example
func lockUserForUpdate(ctx context.Context, userID int) (*User, error) {
    conn, err := pgx.Connect(ctx, "postgres://postgres:secret@localhost:5432/mydb")
    if err != nil {
        return nil, err
    }
    defer conn.Close(ctx)

    tx, err := conn.Begin(ctx)
    if err != nil {
        return nil, err
    }
    defer tx.Rollback(ctx)

    var user User
    err = tx.QueryRow(ctx,
        `SELECT id, username, email
         FROM test_schema.users
         WHERE id = $1
         FOR UPDATE NOWAIT`,
        userID,
    ).Scan(&user.ID, &user.Username, &user.Email)

    if err != nil {
        return nil, err
    }

    if err := tx.Commit(ctx); err != nil {
        return nil, err
    }

    return &user, nil
}

func main() {
    fmt.Println("Database client examples")
}
