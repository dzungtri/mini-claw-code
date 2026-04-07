use std::process::{exit, Command};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    match args.first().map(|s| s.as_str()) {
        Some("check") => check("mini-claw-code-starter"),
        Some("solution-check") => check("mini-claw-code"),
        Some("book") => book(),
        Some("book-zh") => book_zh(),
        Some("book-vi") => book_vi(),
        Some("book-build") => book_build(),
        Some(cmd) => {
            eprintln!("Unknown command: {cmd}");
            usage();
            exit(1);
        }
        None => {
            usage();
            exit(1);
        }
    }
}

fn usage() {
    eprintln!("Usage: cargo x <command>");
    eprintln!("Commands: check, solution-check, book, book-zh, book-vi, book-build");
}

fn check(package: &str) {
    println!("Checking {package}...\n");

    run("cargo", &["fmt", "--check", "-p", package], "fmt");
    run(
        "cargo",
        &["clippy", "-p", package, "--", "-D", "warnings"],
        "clippy",
    );
    run("cargo", &["test", "-p", package], "test");

    println!("\nAll checks passed for {package}!");
}

fn run(cmd: &str, args: &[&str], label: &str) {
    println!("--- {label} ---");
    let status = Command::new(cmd).args(args).status().unwrap_or_else(|e| {
        eprintln!("Failed to run {cmd}: {e}");
        exit(1);
    });

    if !status.success() {
        eprintln!("\n{label} failed!");
        exit(1);
    }
    println!();
}

fn book() {
    println!("Building and serving mdbook (English)...");
    let status = Command::new("mdbook")
        .args(["serve", "mini-claw-code-book"])
        .status()
        .unwrap_or_else(|e| {
            eprintln!("Failed to run mdbook: {e}");
            eprintln!("Install mdbook with: cargo install mdbook");
            exit(1);
        });

    if !status.success() {
        exit(1);
    }
}

fn book_zh() {
    serve_localized_book("Chinese", "book.zh.toml");
}

fn book_vi() {
    serve_localized_book("Vietnamese", "book.vi.toml");
}

fn book_build() {
    println!("Building all books...\n");

    let book_dir = "mini-claw-code-book";

    // Build English
    println!("--- English ---");
    let status = Command::new("mdbook")
        .args(["build", book_dir])
        .status()
        .unwrap_or_else(|e| {
            eprintln!("Failed to run mdbook: {e}");
            exit(1);
        });
    if !status.success() {
        eprintln!("English build failed!");
        exit(1);
    }

    build_localized_book("Chinese", "book.zh.toml");
    build_localized_book("Vietnamese", "book.vi.toml");

    // Copy landing page
    let src = format!("{book_dir}/index.html");
    let dst = format!("{book_dir}/book/index.html");
    std::fs::copy(&src, &dst).unwrap_or_else(|e| {
        eprintln!("Failed to copy landing page: {e}");
        exit(1);
    });

    println!("\nAll books built to {book_dir}/book/");
}

fn serve_localized_book(language: &str, localized_toml_name: &str) {
    println!("Building and serving mdbook ({language})...");

    let book_dir = "mini-claw-code-book";
    let toml_path = format!("{book_dir}/book.toml");
    let localized_toml_path = format!("{book_dir}/{localized_toml_name}");
    let original = swap_book_config(&toml_path, &localized_toml_path);

    let status = Command::new("mdbook")
        .args(["serve", book_dir])
        .status()
        .unwrap_or_else(|e| {
            let _ = std::fs::write(&toml_path, &original);
            eprintln!("Failed to run mdbook: {e}");
            eprintln!("Install mdbook with: cargo install mdbook");
            exit(1);
        });

    restore_book_config(&toml_path, &original);

    if !status.success() {
        exit(1);
    }
}

fn build_localized_book(language: &str, localized_toml_name: &str) {
    let book_dir = "mini-claw-code-book";
    let toml_path = format!("{book_dir}/book.toml");
    let localized_toml_path = format!("{book_dir}/{localized_toml_name}");

    println!("--- {language} ---");
    let original = swap_book_config(&toml_path, &localized_toml_path);

    let status = Command::new("mdbook")
        .args(["build", book_dir])
        .status()
        .unwrap_or_else(|e| {
            let _ = std::fs::write(&toml_path, &original);
            eprintln!("Failed to run mdbook: {e}");
            exit(1);
        });

    restore_book_config(&toml_path, &original);

    if !status.success() {
        eprintln!("{language} build failed!");
        exit(1);
    }
}

fn swap_book_config(toml_path: &str, localized_toml_path: &str) -> String {
    let original = std::fs::read_to_string(toml_path).unwrap_or_else(|e| {
        eprintln!("Failed to read {toml_path}: {e}");
        exit(1);
    });
    let localized_config = std::fs::read_to_string(localized_toml_path).unwrap_or_else(|e| {
        eprintln!("Failed to read {localized_toml_path}: {e}");
        exit(1);
    });

    std::fs::write(toml_path, &localized_config).unwrap_or_else(|e| {
        eprintln!("Failed to write {toml_path}: {e}");
        exit(1);
    });

    original
}

fn restore_book_config(toml_path: &str, original: &str) {
    std::fs::write(toml_path, original).unwrap_or_else(|e| {
        eprintln!("Failed to restore {toml_path}: {e}");
        exit(1);
    });
}
