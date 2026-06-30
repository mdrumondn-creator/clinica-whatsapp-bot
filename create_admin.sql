INSERT INTO usuario (nome, login, senha_hash, perfil, ativo) 
VALUES ('Administrador', 'admin', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918', 'admin', TRUE) 
ON CONFLICT (login) DO UPDATE SET senha_hash='8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918';
