# Week 1 CSV Examples

This folder contains one integrated CSV and six logical subtables for the Week 1 customer onboarding example.

## Master CSV

- `customer_examples_master.csv`

The master file contains all example rows from Customers A, B, and C. It uses metadata columns to identify each row:

- `source_system`: source customer system, such as `customer_a_us`
- `source_table`: logical subtable name, such as `customer_a_customers`
- `entity_type`: `customers` or `orders`
- `source_row_number`: row number inside the original subtable

## Logical subtables

These files are the child tables of the master CSV:

- `customer_a_customers.csv`
- `customer_a_orders.csv`
- `customer_b_customers.csv`
- `customer_b_orders.csv`
- `customer_c_customers.csv`
- `customer_c_orders.csv`

To recreate a subtable from the master CSV, filter by `source_table`.

Example:

```text
source_table = customer_b_orders
```

The master CSV keeps the union of all source columns. Columns that do not apply to a row are left blank.
