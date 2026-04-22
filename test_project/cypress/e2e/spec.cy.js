describe('User Registration', function() {
  it('should register a user and redirect to the main page', function() {
    cy.visit('/register.html');
    
    // Fill in Full name, email, and password fields with mock data
    cy.get('#name').type('Test User');
    cy.get('#email').type('testuser@example.com');
    cy.get('#password').type('123456');
    
    // Click on Sign up button
    cy.get('#register-btn').click();
    
    // Assert that the user has been redirected to the main page
    cy.url().should('contain', '/index.html');
  });
});