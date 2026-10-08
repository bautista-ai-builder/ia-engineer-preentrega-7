# Arquitectura
La API usa PostgreSQL como fuente de verdad de pedidos. Redis almacena caché y estados temporales. Las escrituras se suspenden si PostgreSQL no está disponible.
