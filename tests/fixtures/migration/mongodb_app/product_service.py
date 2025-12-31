"""
Product service with MongoDB access patterns.
"""
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson import ObjectId


class ProductService:
    def __init__(self, connection_uri: str):
        self.client = MongoClient(connection_uri)
        self.db = self.client.ecommerce
        self.products = self.db.products
        self.reviews = self.db.reviews

    def get_products_with_reviews(self):
        """Get products with aggregated review data using MongoDB aggregation pipeline."""
        # MongoDB aggregation pipeline
        pipeline = [
            {
                "$lookup": {
                    "from": "reviews",
                    "localField": "_id",
                    "foreignField": "product_id",
                    "as": "reviews"
                }
            },
            {
                "$addFields": {
                    "avg_rating": {"$avg": "$reviews.rating"},
                    "review_count": {"$size": "$reviews"}
                }
            },
            {
                "$match": {
                    "review_count": {"$gte": 5}
                }
            },
            {
                "$sort": {"avg_rating": -1}
            },
            {
                "$limit": 50
            }
        ]
        return list(self.products.aggregate(pipeline))

    def update_product_stock(self, product_id: str, quantity: int):
        """Update product stock using MongoDB update operators."""
        # MongoDB $inc operator
        result = self.products.update_one(
            {"_id": ObjectId(product_id)},
            {
                "$inc": {"stock_quantity": quantity},
                "$set": {"updated_at": datetime.utcnow()},
                "$push": {
                    "stock_history": {
                        "date": datetime.utcnow(),
                        "change": quantity,
                        "type": "adjustment"
                    }
                }
            }
        )
        return result.modified_count > 0

    def add_product_with_nested_data(self, product_data: dict):
        """Add product with embedded documents (MongoDB pattern)."""
        # Embedded document structure
        product = {
            "name": product_data["name"],
            "description": product_data["description"],
            "price": product_data["price"],
            "category": product_data["category"],
            "attributes": {
                "color": product_data.get("color"),
                "size": product_data.get("size"),
                "weight": product_data.get("weight")
            },
            "images": [
                {"url": img, "order": idx}
                for idx, img in enumerate(product_data.get("images", []))
            ],
            "stock_history": [],
            "tags": product_data.get("tags", []),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        result = self.products.insert_one(product)
        return str(result.inserted_id)

    def search_products(self, search_term: str, filters: dict = None):
        """Search products using MongoDB query operators."""
        query = {}

        # Text search (MongoDB text index)
        if search_term:
            query["$text"] = {"$search": search_term}

        # Apply filters with MongoDB operators
        if filters:
            if "min_price" in filters:
                query["price"] = query.get("price", {})
                query["price"]["$gte"] = filters["min_price"]
            if "max_price" in filters:
                query["price"] = query.get("price", {})
                query["price"]["$lte"] = filters["max_price"]
            if "categories" in filters:
                query["category"] = {"$in": filters["categories"]}
            if "tags" in filters:
                query["tags"] = {"$all": filters["tags"]}

        # Use projection to exclude some fields
        projection = {"stock_history": 0}

        return list(self.products.find(query, projection).limit(100))

    def get_category_stats(self):
        """Get category statistics using MongoDB aggregation."""
        pipeline = [
            {
                "$group": {
                    "_id": "$category",
                    "product_count": {"$sum": 1},
                    "avg_price": {"$avg": "$price"},
                    "min_price": {"$min": "$price"},
                    "max_price": {"$max": "$price"},
                    "total_stock": {"$sum": "$stock_quantity"}
                }
            },
            {
                "$sort": {"product_count": -1}
            }
        ]
        return list(self.products.aggregate(pipeline))

    def get_trending_products(self, days: int = 7):
        """Get trending products with complex aggregation pipeline."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            # Join with orders
            {
                "$lookup": {
                    "from": "order_items",
                    "localField": "_id",
                    "foreignField": "product_id",
                    "as": "order_items"
                }
            },
            # Unwind order items
            {
                "$unwind": {
                    "path": "$order_items",
                    "preserveNullAndEmptyArrays": False
                }
            },
            # Filter by date
            {
                "$match": {
                    "order_items.created_at": {"$gte": cutoff_date}
                }
            },
            # Group and calculate metrics
            {
                "$group": {
                    "_id": "$_id",
                    "name": {"$first": "$name"},
                    "category": {"$first": "$category"},
                    "price": {"$first": "$price"},
                    "order_count": {"$sum": 1},
                    "revenue": {"$sum": {"$multiply": ["$order_items.quantity", "$price"]}},
                    "avg_quantity": {"$avg": "$order_items.quantity"}
                }
            },
            # Calculate trend score
            {
                "$addFields": {
                    "trend_score": {
                        "$add": [
                            {"$multiply": ["$order_count", 2]},
                            {"$divide": ["$revenue", 100]}
                        ]
                    }
                }
            },
            # Sort and limit
            {
                "$sort": {"trend_score": -1}
            },
            {
                "$limit": 20
            }
        ]
        return list(self.products.aggregate(pipeline))

    def update_product_ratings(self):
        """Bulk update product ratings using MongoDB aggregation in update."""
        # Use aggregation pipeline in update (MongoDB 4.2+)
        pipeline = [
            {
                "$lookup": {
                    "from": "reviews",
                    "localField": "_id",
                    "foreignField": "product_id",
                    "as": "reviews"
                }
            },
            {
                "$set": {
                    "avg_rating": {"$avg": "$reviews.rating"},
                    "review_count": {"$size": "$reviews"},
                    "updated_at": datetime.utcnow()
                }
            },
            {
                "$unset": "reviews"
            }
        ]

        # Update all products
        self.products.update_many({}, pipeline)

    def archive_old_products(self):
        """Archive old products using MongoDB operators."""
        cutoff_date = datetime.utcnow() - timedelta(days=365 * 2)

        # Find products to archive
        old_products = self.products.find({
            "updated_at": {"$lt": cutoff_date},
            "stock_quantity": {"$eq": 0}
        })

        # Move to archive collection
        archived_count = 0
        for product in old_products:
            self.db.products_archive.insert_one(product)
            self.products.delete_one({"_id": product["_id"]})
            archived_count += 1

        return archived_count
