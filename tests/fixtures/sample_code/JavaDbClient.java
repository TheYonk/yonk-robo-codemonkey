// Sample Java database client using various libraries
package com.example.db;

import java.sql.*;
import java.util.*;
import javax.persistence.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.transaction.annotation.Transactional;
import org.flywaydb.core.Flyway;

/**
 * Database client examples for Java with JDBC, JPA, Spring, and Flyway.
 */
public class JavaDbClient {

    // JDBC example
    public static User getUserWithJDBC(int userId) throws SQLException {
        String url = "jdbc:postgresql://localhost:5432/mydb";
        String username = "postgres";
        String password = "secret";

        try (Connection conn = DriverManager.getConnection(url, username, password)) {
            String sql = "SELECT id, username, email FROM test_schema.users WHERE id = ?";

            try (PreparedStatement stmt = conn.prepareStatement(sql)) {
                stmt.setInt(1, userId);

                try (ResultSet rs = stmt.executeQuery()) {
                    if (rs.next()) {
                        User user = new User();
                        user.setId(rs.getInt("id"));
                        user.setUsername(rs.getString("username"));
                        user.setEmail(rs.getString("email"));
                        return user;
                    }
                }
            }
        }
        return null;
    }

    // JDBC transaction example
    public static String createOrderWithJDBC(int userId, double totalAmount) throws SQLException {
        String url = "jdbc:postgresql://localhost:5432/mydb";
        String username = "postgres";
        String password = "secret";

        try (Connection conn = DriverManager.getConnection(url, username, password)) {
            conn.setAutoCommit(false);

            try {
                String sql = "INSERT INTO test_schema.orders (user_id, total_amount, status) " +
                           "VALUES (?, ?, 'pending') RETURNING id";

                String orderId;
                try (PreparedStatement stmt = conn.prepareStatement(sql)) {
                    stmt.setInt(1, userId);
                    stmt.setDouble(2, totalAmount);

                    try (ResultSet rs = stmt.executeQuery()) {
                        if (rs.next()) {
                            orderId = rs.getString("id");
                        } else {
                            throw new SQLException("Failed to create order");
                        }
                    }
                }

                conn.commit();
                return orderId;
            } catch (SQLException e) {
                conn.rollback();
                throw e;
            }
        }
    }

    // Spring JdbcTemplate example
    private JdbcTemplate jdbcTemplate;

    public List<Order> getOrdersWithSpring(int userId) {
        String sql = "SELECT id, user_id, total_amount, status " +
                    "FROM test_schema.orders " +
                    "WHERE user_id = ? " +
                    "ORDER BY created_at DESC";

        return jdbcTemplate.query(sql, new Object[]{userId}, new RowMapper<Order>() {
            @Override
            public Order mapRow(ResultSet rs, int rowNum) throws SQLException {
                Order order = new Order();
                order.setId(rs.getString("id"));
                order.setUserId(rs.getInt("user_id"));
                order.setTotalAmount(rs.getDouble("total_amount"));
                order.setStatus(rs.getString("status"));
                return order;
            }
        });
    }

    // Spring JdbcTemplate update
    public int updateOrderStatus(String orderId, String status) {
        String sql = "UPDATE test_schema.orders SET status = ? WHERE id = ?";
        return jdbcTemplate.update(sql, status, orderId);
    }

    // JPA/Hibernate entity
    @Entity
    @Table(name = "users", schema = "test_schema")
    public static class UserEntity {
        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        private Integer id;

        @Column(length = 100)
        private String username;

        @Column(length = 255)
        private String email;

        // Getters and setters
        public Integer getId() { return id; }
        public void setId(Integer id) { this.id = id; }
        public String getUsername() { return username; }
        public void setUsername(String username) { this.username = username; }
        public String getEmail() { return email; }
        public void setEmail(String email) { this.email = email; }
    }

    // JPA EntityManager example
    @PersistenceContext
    private EntityManager entityManager;

    public UserEntity getUserWithJPA(int userId) {
        return entityManager.find(UserEntity.class, userId);
    }

    // JPA JPQL query
    public List<UserEntity> searchUsersJPQL(String searchTerm) {
        String jpql = "SELECT u FROM UserEntity u WHERE u.username LIKE :searchTerm";

        TypedQuery<UserEntity> query = entityManager.createQuery(jpql, UserEntity.class);
        query.setParameter("searchTerm", "%" + searchTerm + "%");

        return query.getResultList();
    }

    // JPA native SQL query
    public List<Order> getOrdersByStatusNative(String status) {
        String sql = "SELECT id, user_id, total_amount, status " +
                    "FROM test_schema.orders " +
                    "WHERE status = ?";

        Query query = entityManager.createNativeQuery(sql, Order.class);
        query.setParameter(1, status);

        return query.getResultList();
    }

    // JPA transaction with @Transactional
    @Transactional
    public String createOrderTransactional(int userId, double totalAmount) {
        OrderEntity order = new OrderEntity();
        order.setUserId(userId);
        order.setTotalAmount(totalAmount);
        order.setStatus("pending");

        entityManager.persist(order);
        entityManager.flush();

        return order.getId();
    }

    // Hibernate Criteria API
    public List<UserEntity> getUsersByCriteria(String email) {
        CriteriaBuilder cb = entityManager.getCriteriaBuilder();
        CriteriaQuery<UserEntity> cq = cb.createQuery(UserEntity.class);
        Root<UserEntity> root = cq.from(UserEntity.class);

        cq.select(root).where(cb.equal(root.get("email"), email));

        return entityManager.createQuery(cq).getResultList();
    }

    // Spring Data JPA Repository (interface)
    public interface UserRepository extends JpaRepository<UserEntity, Integer> {
        List<UserEntity> findByUsername(String username);

        @Query("SELECT u FROM UserEntity u WHERE u.email LIKE %:domain%")
        List<UserEntity> findByEmailDomain(@Param("domain") String domain);

        @Query(value = "SELECT * FROM test_schema.users WHERE created_at > ?1", nativeQuery = true)
        List<UserEntity> findRecentUsers(Timestamp since);
    }

    // Flyway migration example
    public static void runMigrations() {
        Flyway flyway = Flyway.configure()
            .dataSource("jdbc:postgresql://localhost:5432/mydb", "postgres", "secret")
            .schemas("test_schema")
            .locations("classpath:db/migration")
            .load();

        flyway.migrate();
    }

    // DDL operation
    public static void createAuditTable() throws SQLException {
        String url = "jdbc:postgresql://localhost:5432/mydb";
        String username = "postgres";
        String password = "secret";

        try (Connection conn = DriverManager.getConnection(url, username, password);
             Statement stmt = conn.createStatement()) {

            String sql = "CREATE TABLE IF NOT EXISTS test_schema.audit_log (" +
                        "id SERIAL PRIMARY KEY, " +
                        "user_id INTEGER REFERENCES test_schema.users(id), " +
                        "action VARCHAR(100), " +
                        "timestamp TIMESTAMPTZ DEFAULT now())";

            stmt.execute(sql);
        }
    }

    // Locking example with SELECT FOR UPDATE
    public User lockUserForUpdate(int userId) throws SQLException {
        String url = "jdbc:postgresql://localhost:5432/mydb";
        String username = "postgres";
        String password = "secret";

        try (Connection conn = DriverManager.getConnection(url, username, password)) {
            conn.setAutoCommit(false);

            try {
                String sql = "SELECT id, username, email " +
                           "FROM test_schema.users " +
                           "WHERE id = ? " +
                           "FOR UPDATE NOWAIT";

                User user;
                try (PreparedStatement stmt = conn.prepareStatement(sql)) {
                    stmt.setInt(1, userId);

                    try (ResultSet rs = stmt.executeQuery()) {
                        if (rs.next()) {
                            user = new User();
                            user.setId(rs.getInt("id"));
                            user.setUsername(rs.getString("username"));
                            user.setEmail(rs.getString("email"));
                        } else {
                            throw new SQLException("User not found");
                        }
                    }
                }

                conn.commit();
                return user;
            } catch (SQLException e) {
                conn.rollback();
                throw e;
            }
        }
    }

    // POJO classes
    public static class User {
        private int id;
        private String username;
        private String email;

        public int getId() { return id; }
        public void setId(int id) { this.id = id; }
        public String getUsername() { return username; }
        public void setUsername(String username) { this.username = username; }
        public String getEmail() { return email; }
        public void setEmail(String email) { this.email = email; }
    }

    public static class Order {
        private String id;
        private int userId;
        private double totalAmount;
        private String status;

        public String getId() { return id; }
        public void setId(String id) { this.id = id; }
        public int getUserId() { return userId; }
        public void setUserId(int userId) { this.userId = userId; }
        public double getTotalAmount() { return totalAmount; }
        public void setTotalAmount(double totalAmount) { this.totalAmount = totalAmount; }
        public String getStatus() { return status; }
        public void setStatus(String status) { this.status = status; }
    }

    @Entity
    @Table(name = "orders", schema = "test_schema")
    public static class OrderEntity {
        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        private String id;
        private int userId;
        private double totalAmount;
        private String status;

        public String getId() { return id; }
        public void setId(String id) { this.id = id; }
        public int getUserId() { return userId; }
        public void setUserId(int userId) { this.userId = userId; }
        public double getTotalAmount() { return totalAmount; }
        public void setTotalAmount(double totalAmount) { this.totalAmount = totalAmount; }
        public String getStatus() { return status; }
        public void setStatus(String status) { this.status = status; }
    }
}
